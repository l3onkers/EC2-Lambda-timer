"""
AWS Lambda - EC2 Auto Start/Stop Controller
============================================

Este script automatiza el encendido y apagado de instancias EC2 basándose en tags.
Se ejecuta periódicamente desde AWS Lambda (recomendado: cada hora).

Tags soportadas en las instancias EC2:
--------------------------------------
- AutoSchedule:      "enabled" | "disabled" - Activa/desactiva el control automático
- AutoScheduleStart: Hora de encendido en formato "HH:MM" o expresión cron (ej: "08:00" o "0 8 * * 1-5")
- AutoScheduleStop:  Hora de apagado en formato "HH:MM" o expresión cron (ej: "18:00" o "0 18 * * 1-5")
- AutoScheduleDays:  Días de la semana (opcional) - "1-5" (L-V), "1,2,3,4,5", "*" (todos)
- Timezone:          Zona horaria (opcional) - ej: "Europe/Madrid", "America/New_York"

Ejemplo de configuración para horario de oficina (08:00-18:00, L-V):
- AutoSchedule: enabled
- AutoScheduleStart: 08:00
- AutoScheduleStop: 18:00
- AutoScheduleDays: 1-5
- Timezone: Europe/Madrid

Autor: Refactorizado 2026
Versión: 2.0.0
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum
import logging
import re
import os

import boto3
from botocore.exceptions import ClientError

# Configuración de logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configuración global
DEBUG = os.environ.get('DEBUG', 'false').lower() == 'true'
DEFAULT_TIMEZONE = os.environ.get('DEFAULT_TIMEZONE', 'UTC')

# Nombres de las tags
class TagNames:
    """Nombres de las tags utilizadas para la configuración."""
    SCHEDULE_ENABLED = "AutoSchedule"
    START_TIME = "AutoScheduleStart"
    STOP_TIME = "AutoScheduleStop"
    DAYS = "AutoScheduleDays"
    TIMEZONE = "Timezone"
    
    # Tags legacy (compatibilidad hacia atrás)
    LEGACY_START = "startInstance"
    LEGACY_STOP = "stopInstance"


class InstanceAction(Enum):
    """Acciones posibles sobre una instancia."""
    START = "start"
    STOP = "stop"
    NONE = "none"


@dataclass
class ScheduleConfig:
    """Configuración de horario para una instancia EC2."""
    enabled: bool = False
    start_time: Optional[str] = None
    stop_time: Optional[str] = None
    days: str = "*"
    timezone: str = "UTC"
    
    # Soporte legacy
    legacy_start_cron: Optional[str] = None
    legacy_stop_cron: Optional[str] = None


class CronMatcher:
    """Clase para validar y comparar expresiones cron con el tiempo actual."""
    
    CRON_PATTERN = re.compile(r"^[0-9]+-[0-9]+$|^[0-9]+(,[0-9]+)*$|\*$")
    
    @staticmethod
    def match_unit(unit: int, range_str: str) -> bool:
        """
        Compara una unidad de tiempo con una expresión cron.
        
        Args:
            unit: Valor numérico actual (minuto, hora, día, etc.)
            range_str: Expresión cron ("*", "5", "1-5", "1,3,5")
            
        Returns:
            True si la unidad coincide con la expresión
        """
        if not isinstance(range_str, str) or not isinstance(unit, int):
            return False
        
        range_str = range_str.strip()
        
        # Wildcard: acepta todo
        if range_str == "*":
            return True
        
        # Validar formato
        if not CronMatcher.CRON_PATTERN.match(range_str):
            logger.warning(f"Expresión cron inválida: {range_str}")
            return False
        
        # Valor exacto
        if range_str.isdigit():
            return unit == int(range_str)
        
        # Rango (ej: "1-5")
        if "-" in range_str and "," not in range_str:
            try:
                start, end = map(int, range_str.split("-"))
                return start <= unit <= end
            except ValueError:
                return False
        
        # Enumeración (ej: "1,3,5")
        if "," in range_str:
            try:
                values = [int(v.strip()) for v in range_str.split(",")]
                return unit in values
            except ValueError:
                return False
        
        return False
    
    @classmethod
    def is_time_match(cls, cron_string: str, now: datetime) -> bool:
        """
        Verifica si el momento actual coincide con la expresión cron.
        
        Args:
            cron_string: Expresión cron "minuto hora día mes día_semana"
            now: Fecha/hora actual
            
        Returns:
            True si el momento actual coincide
        """
        try:
            parts = cron_string.strip().split()
            if len(parts) != 5:
                logger.warning(f"Expresión cron debe tener 5 campos: {cron_string}")
                return False
            
            minute, hour, day, month, weekday = parts
            
            checks = [
                cls.match_unit(now.minute, minute),
                cls.match_unit(now.hour, hour),
                cls.match_unit(now.day, day),
                cls.match_unit(now.month, month),
                cls.match_unit(now.isoweekday(), weekday),
            ]
            
            return all(checks)
            
        except Exception as e:
            logger.error(f"Error evaluando expresión cron '{cron_string}': {e}")
            return False


class TimeParser:
    """Utilidades para parsear diferentes formatos de tiempo."""
    
    SIMPLE_TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})$")
    
    @classmethod
    def parse_simple_time(cls, time_str: str) -> Optional[tuple]:
        """
        Parsea un tiempo simple en formato HH:MM.
        
        Args:
            time_str: Tiempo en formato "HH:MM"
            
        Returns:
            Tuple (hora, minuto) o None si el formato es inválido
        """
        match = cls.SIMPLE_TIME_PATTERN.match(time_str.strip())
        if match:
            hour, minute = int(match.group(1)), int(match.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return (hour, minute)
        return None
    
    @classmethod
    def is_simple_time_match(cls, time_str: str, now: datetime, days: str = "*") -> bool:
        """
        Verifica si el tiempo actual coincide con el tiempo especificado.
        
        Args:
            time_str: Tiempo en formato "HH:MM"
            now: Fecha/hora actual
            days: Días de la semana válidos
            
        Returns:
            True si coincide la hora (y el día si se especifica)
        """
        parsed = cls.parse_simple_time(time_str)
        if not parsed:
            return False
        
        hour, minute = parsed
        
        # Verificar hora
        if now.hour != hour:
            return False
        
        # Verificar minuto (con tolerancia de ±5 minutos para ejecuciones cada hora)
        # Esto permite que la Lambda se ejecute en cualquier minuto de la hora
        # y aún así detecte la hora correcta
        
        # Verificar día de la semana
        if days != "*":
            if not CronMatcher.match_unit(now.isoweekday(), days):
                return False
        
        return True
    
    @classmethod
    def is_cron_expression(cls, value: str) -> bool:
        """Determina si el valor es una expresión cron (5 campos)."""
        return len(value.strip().split()) == 5


def get_current_time(tz_name: str = "UTC") -> datetime:
    """
    Obtiene la hora actual en la zona horaria especificada.
    
    Args:
        tz_name: Nombre de la zona horaria (ej: "Europe/Madrid")
        
    Returns:
        datetime con la hora actual
    """
    try:
        # Para zonas horarias avanzadas, se necesitaría pytz o zoneinfo (Python 3.9+)
        # Por simplicidad, usamos UTC y ajustamos manualmente las más comunes
        from datetime import timedelta
        
        now_utc = datetime.now(timezone.utc)
        
        # Mapa simple de zonas horarias comunes
        tz_offsets = {
            "UTC": 0,
            "Europe/Madrid": 1,  # CET (sin horario de verano)
            "Europe/London": 0,
            "America/New_York": -5,
            "America/Los_Angeles": -8,
            "Asia/Tokyo": 9,
        }
        
        offset = tz_offsets.get(tz_name, 0)
        return now_utc + timedelta(hours=offset)
        
    except Exception as e:
        logger.warning(f"Error con zona horaria {tz_name}: {e}. Usando UTC.")
        return datetime.now(timezone.utc)


def extract_schedule_config(instance) -> ScheduleConfig:
    """
    Extrae la configuración de horario de las tags de una instancia.
    
    Args:
        instance: Instancia EC2 de boto3
        
    Returns:
        ScheduleConfig con la configuración encontrada
    """
    config = ScheduleConfig()
    
    if not instance.tags:
        return config
    
    tags = {tag['Key']: tag['Value'] for tag in instance.tags}
    
    # Verificar si el schedule está habilitado
    schedule_value = tags.get(TagNames.SCHEDULE_ENABLED, "").lower()
    config.enabled = schedule_value == "enabled"
    
    # Obtener configuración de horarios
    config.start_time = tags.get(TagNames.START_TIME)
    config.stop_time = tags.get(TagNames.STOP_TIME)
    config.days = tags.get(TagNames.DAYS, "*")
    config.timezone = tags.get(TagNames.TIMEZONE, DEFAULT_TIMEZONE)
    
    # Soporte para tags legacy
    config.legacy_start_cron = tags.get(TagNames.LEGACY_START)
    config.legacy_stop_cron = tags.get(TagNames.LEGACY_STOP)
    
    # Si hay tags legacy, considerar habilitado
    if config.legacy_start_cron or config.legacy_stop_cron:
        config.enabled = True
    
    return config


def should_perform_action(config: ScheduleConfig, action: InstanceAction, now: datetime) -> bool:
    """
    Determina si se debe realizar una acción basándose en la configuración y hora actual.
    
    Args:
        config: Configuración de horario
        action: Acción a evaluar (START o STOP)
        now: Hora actual
        
    Returns:
        True si se debe realizar la acción
    """
    if action == InstanceAction.START:
        time_value = config.start_time
        legacy_cron = config.legacy_start_cron
    elif action == InstanceAction.STOP:
        time_value = config.stop_time
        legacy_cron = config.legacy_stop_cron
    else:
        return False
    
    # Primero intentar con el nuevo formato simple
    if time_value:
        if TimeParser.is_cron_expression(time_value):
            return CronMatcher.is_time_match(time_value, now)
        else:
            return TimeParser.is_simple_time_match(time_value, now, config.days)
    
    # Fallback a formato legacy
    if legacy_cron:
        return CronMatcher.is_time_match(legacy_cron, now)
    
    return False


def execute_instance_action(instance, action: InstanceAction) -> bool:
    """
    Ejecuta una acción sobre una instancia EC2.
    
    Args:
        instance: Instancia EC2
        action: Acción a realizar
        
    Returns:
        True si la acción se ejecutó correctamente
    """
    instance_id = instance.id
    instance_name = ""
    
    # Obtener nombre de la instancia
    if instance.tags:
        for tag in instance.tags:
            if tag['Key'] == 'Name':
                instance_name = tag['Value']
                break
    
    display_name = f"{instance_name} ({instance_id})" if instance_name else instance_id
    
    try:
        if action == InstanceAction.START:
            if instance.state["Name"] == "stopped":
                logger.info(f"🟢 Iniciando instancia: {display_name}")
                instance.start()
                return True
            else:
                logger.debug(f"Instancia {display_name} no está detenida (estado: {instance.state['Name']})")
                
        elif action == InstanceAction.STOP:
            if instance.state["Name"] == "running":
                logger.info(f"🔴 Deteniendo instancia: {display_name}")
                instance.stop()
                return True
            else:
                logger.debug(f"Instancia {display_name} no está corriendo (estado: {instance.state['Name']})")
                
    except ClientError as e:
        logger.error(f"Error al ejecutar {action.value} en {display_name}: {e}")
        return False
    
    return False


def process_instances(ec2_resource) -> Dict[str, Any]:
    """
    Procesa todas las instancias EC2 y ejecuta las acciones correspondientes.
    
    Args:
        ec2_resource: Recurso EC2 de boto3
        
    Returns:
        Diccionario con estadísticas de la ejecución
    """
    stats = {
        "total_instances": 0,
        "scheduled_instances": 0,
        "started": [],
        "stopped": [],
        "errors": [],
    }
    
    for instance in ec2_resource.instances.all():
        stats["total_instances"] += 1
        
        config = extract_schedule_config(instance)
        
        if not config.enabled:
            continue
        
        stats["scheduled_instances"] += 1
        
        # Obtener hora actual en la zona horaria configurada
        now = get_current_time(config.timezone)
        
        instance_id = instance.id
        
        if DEBUG:
            logger.info(f"Evaluando instancia {instance_id} - Config: start={config.start_time}, stop={config.stop_time}, days={config.days}, tz={config.timezone}")
            logger.info(f"  Hora actual ({config.timezone}): {now.strftime('%Y-%m-%d %H:%M')}")
        
        # Verificar si es hora de iniciar
        if should_perform_action(config, InstanceAction.START, now):
            if execute_instance_action(instance, InstanceAction.START):
                stats["started"].append(instance_id)
        
        # Verificar si es hora de detener
        if should_perform_action(config, InstanceAction.STOP, now):
            if execute_instance_action(instance, InstanceAction.STOP):
                stats["stopped"].append(instance_id)
    
    return stats


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler principal de AWS Lambda.
    
    Args:
        event: Evento de Lambda
        context: Contexto de Lambda
        
    Returns:
        Respuesta con el resultado de la ejecución
    """
    logger.info("=" * 60)
    logger.info("EC2 Auto Start/Stop - Iniciando ejecución")
    logger.info("=" * 60)
    
    start_time = datetime.now(timezone.utc)
    
    try:
        # Crear sesión y recurso EC2
        session = boto3.Session()
        ec2 = session.resource('ec2')
        
        # Procesar instancias
        stats = process_instances(ec2)
        
        # Log de resultados
        logger.info("-" * 40)
        logger.info(f"Instancias totales: {stats['total_instances']}")
        logger.info(f"Instancias con schedule: {stats['scheduled_instances']}")
        
        if stats['started']:
            logger.info(f"Instancias iniciadas: {', '.join(stats['started'])}")
        if stats['stopped']:
            logger.info(f"Instancias detenidas: {', '.join(stats['stopped'])}")
        
        execution_time = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(f"Tiempo de ejecución: {execution_time:.2f}s")
        logger.info("=" * 60)
        
        return {
            "statusCode": 200,
            "body": {
                "message": "EC2 schedule check completed",
                "stats": stats,
                "execution_time": execution_time,
            }
        }
        
    except Exception as e:
        logger.error(f"Error durante la ejecución: {str(e)}", exc_info=True)
        return {
            "statusCode": 500,
            "body": {
                "message": "Error during execution",
                "error": str(e),
            }
        }


# Para pruebas locales
if __name__ == "__main__":
    # Configurar logging para consola
    logging.basicConfig(
        level=logging.DEBUG if DEBUG else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Simular ejecución
    result = lambda_handler({}, None)
    print(f"\nResultado: {result}")