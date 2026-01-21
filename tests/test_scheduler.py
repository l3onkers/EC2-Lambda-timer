"""
Tests para EC2 Auto Start/Stop Lambda
=====================================

Ejecutar con: python -m pytest tests/ -v
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
import sys
import os

# Añadir el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EC2StopStart import (
    CronMatcher,
    TimeParser,
    ScheduleConfig,
    extract_schedule_config,
    should_perform_action,
    InstanceAction,
)


class TestCronMatcher:
    """Tests para la clase CronMatcher."""
    
    def test_match_wildcard(self):
        """Wildcard debe coincidir con cualquier valor."""
        assert CronMatcher.match_unit(0, "*") is True
        assert CronMatcher.match_unit(59, "*") is True
        assert CronMatcher.match_unit(23, "*") is True
    
    def test_match_exact_value(self):
        """Valor exacto debe coincidir solo con ese valor."""
        assert CronMatcher.match_unit(8, "8") is True
        assert CronMatcher.match_unit(8, "9") is False
        assert CronMatcher.match_unit(0, "0") is True
    
    def test_match_range(self):
        """Rangos deben coincidir con valores dentro del rango."""
        assert CronMatcher.match_unit(3, "1-5") is True
        assert CronMatcher.match_unit(1, "1-5") is True
        assert CronMatcher.match_unit(5, "1-5") is True
        assert CronMatcher.match_unit(6, "1-5") is False
        assert CronMatcher.match_unit(0, "1-5") is False
    
    def test_match_enumeration(self):
        """Enumeraciones deben coincidir con valores en la lista."""
        assert CronMatcher.match_unit(1, "1,3,5") is True
        assert CronMatcher.match_unit(3, "1,3,5") is True
        assert CronMatcher.match_unit(5, "1,3,5") is True
        assert CronMatcher.match_unit(2, "1,3,5") is False
        assert CronMatcher.match_unit(4, "1,3,5") is False
    
    def test_invalid_types(self):
        """Tipos inválidos deben retornar False."""
        assert CronMatcher.match_unit("8", "8") is False
        assert CronMatcher.match_unit(8, 8) is False
        assert CronMatcher.match_unit(None, "*") is False
    
    def test_invalid_format(self):
        """Formatos inválidos deben retornar False."""
        assert CronMatcher.match_unit(8, "abc") is False
        assert CronMatcher.match_unit(8, "8-") is False
        assert CronMatcher.match_unit(8, "-8") is False
    
    def test_is_time_match_full_cron(self):
        """Expresión cron completa debe evaluarse correctamente."""
        # Crear un datetime específico: Lunes 8:00
        test_time = datetime(2026, 1, 19, 8, 0)  # Lunes
        
        assert CronMatcher.is_time_match("0 8 * * 1", test_time) is True
        assert CronMatcher.is_time_match("0 8 * * 1-5", test_time) is True
        assert CronMatcher.is_time_match("0 9 * * 1", test_time) is False
        assert CronMatcher.is_time_match("0 8 * * 6", test_time) is False  # Sábado


class TestTimeParser:
    """Tests para la clase TimeParser."""
    
    def test_parse_simple_time_valid(self):
        """Tiempos válidos deben parsearse correctamente."""
        assert TimeParser.parse_simple_time("08:00") == (8, 0)
        assert TimeParser.parse_simple_time("18:30") == (18, 30)
        assert TimeParser.parse_simple_time("0:00") == (0, 0)
        assert TimeParser.parse_simple_time("23:59") == (23, 59)
    
    def test_parse_simple_time_invalid(self):
        """Tiempos inválidos deben retornar None."""
        assert TimeParser.parse_simple_time("25:00") is None
        assert TimeParser.parse_simple_time("12:60") is None
        assert TimeParser.parse_simple_time("invalid") is None
        assert TimeParser.parse_simple_time("8:0:0") is None
    
    def test_is_cron_expression(self):
        """Detectar si es expresión cron."""
        assert TimeParser.is_cron_expression("0 8 * * 1-5") is True
        assert TimeParser.is_cron_expression("08:00") is False
        assert TimeParser.is_cron_expression("* * * * *") is True
    
    def test_is_simple_time_match(self):
        """Verificar coincidencia de tiempo simple."""
        test_time = datetime(2026, 1, 19, 8, 0)  # Lunes 8:00
        
        assert TimeParser.is_simple_time_match("08:00", test_time, "*") is True
        assert TimeParser.is_simple_time_match("08:00", test_time, "1-5") is True
        assert TimeParser.is_simple_time_match("09:00", test_time, "*") is False
        assert TimeParser.is_simple_time_match("08:00", test_time, "6-7") is False


class TestScheduleConfig:
    """Tests para extracción de configuración."""
    
    def test_extract_new_format(self):
        """Extraer configuración con formato nuevo."""
        mock_instance = Mock()
        mock_instance.tags = [
            {"Key": "AutoSchedule", "Value": "enabled"},
            {"Key": "AutoScheduleStart", "Value": "08:00"},
            {"Key": "AutoScheduleStop", "Value": "18:00"},
            {"Key": "AutoScheduleDays", "Value": "1-5"},
            {"Key": "Timezone", "Value": "Europe/Madrid"},
        ]
        
        config = extract_schedule_config(mock_instance)
        
        assert config.enabled is True
        assert config.start_time == "08:00"
        assert config.stop_time == "18:00"
        assert config.days == "1-5"
        assert config.timezone == "Europe/Madrid"
    
    def test_extract_legacy_format(self):
        """Extraer configuración con formato legacy."""
        mock_instance = Mock()
        mock_instance.tags = [
            {"Key": "startInstance", "Value": "0 8 * * 1-5"},
            {"Key": "stopInstance", "Value": "0 18 * * 1-5"},
        ]
        
        config = extract_schedule_config(mock_instance)
        
        assert config.enabled is True  # Se habilita automáticamente con tags legacy
        assert config.legacy_start_cron == "0 8 * * 1-5"
        assert config.legacy_stop_cron == "0 18 * * 1-5"
    
    def test_extract_no_tags(self):
        """Instancia sin tags debe retornar config deshabilitada."""
        mock_instance = Mock()
        mock_instance.tags = None
        
        config = extract_schedule_config(mock_instance)
        
        assert config.enabled is False


class TestShouldPerformAction:
    """Tests para la lógica de decidir acciones."""
    
    def test_start_action_new_format(self):
        """Verificar acción START con formato nuevo."""
        config = ScheduleConfig(
            enabled=True,
            start_time="08:00",
            stop_time="18:00",
            days="1-5",
        )
        
        # Lunes 8:00
        test_time = datetime(2026, 1, 19, 8, 0)
        assert should_perform_action(config, InstanceAction.START, test_time) is True
        
        # Lunes 9:00 - no es hora de start
        test_time = datetime(2026, 1, 19, 9, 0)
        assert should_perform_action(config, InstanceAction.START, test_time) is False
    
    def test_stop_action_new_format(self):
        """Verificar acción STOP con formato nuevo."""
        config = ScheduleConfig(
            enabled=True,
            start_time="08:00",
            stop_time="18:00",
            days="1-5",
        )
        
        # Lunes 18:00
        test_time = datetime(2026, 1, 19, 18, 0)
        assert should_perform_action(config, InstanceAction.STOP, test_time) is True
    
    def test_weekend_not_scheduled(self):
        """Fines de semana no deben coincidir con días laborables."""
        config = ScheduleConfig(
            enabled=True,
            start_time="08:00",
            stop_time="18:00",
            days="1-5",
        )
        
        # Sábado 8:00
        test_time = datetime(2026, 1, 24, 8, 0)
        assert should_perform_action(config, InstanceAction.START, test_time) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
