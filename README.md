# EC2 Auto Start/Stop Lambda

**Script de AWS Lambda (Python) para iniciar y detener automáticamente instancias EC2** basándose en etiquetas (tags) configuradas en cada instancia.

Ideal para:
- **Reducir costos** apagando instancias fuera del horario laboral
- **Automatizar** el encendido/apagado sin intervención manual
- **Entornos de desarrollo/test** que solo necesitan estar activos durante el día

---

## Tabla de Contenidos

- [Características](#-características)
- [Instalación](#-instalación)
- [Configuración de Tags](#-configuración-de-tags)
- [Ejemplos](#-ejemplos)
- [Configuración de Lambda](#-configuración-de-lambda)
- [Variables de Entorno](#-variables-de-entorno)
- [Compatibilidad](#-compatibilidad)

---

## Características

- **Formato de hora simple**: Usa `HH:MM` (ej: `08:00`, `18:00`)
- **Expresiones cron completas**: Para configuraciones avanzadas
- **Soporte de días de la semana**: Define qué días aplicar el schedule
- **Zonas horarias**: Configura la zona horaria por instancia
- **Tag de habilitación**: Activa/desactiva el control por instancia
- **Compatibilidad legacy**: Soporta las tags antiguas (`startInstance`/`stopInstance`)
- **Logging detallado**: Fácil seguimiento y debugging

---

## Instalación

### 1. Crear la función Lambda

1. Ve a AWS Lambda Console
2. Crea una nueva función con Python 3.9+
3. Copia el contenido de `EC2StopStart.py`
4. Configura el handler: `EC2StopStart.lambda_handler`

### 2. Configurar permisos IAM

La función Lambda necesita un rol con los siguientes permisos:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeInstances",
                "ec2:DescribeTags",
                "ec2:StartInstances",
                "ec2:StopInstances"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "arn:aws:logs:*:*:*"
        }
    ]
}
```

### 3. Configurar EventBridge (CloudWatch Events)

Crea una regla para ejecutar la Lambda cada hora:

```
Expresión cron: cron(0 * * * ? *)
```

O cada 30 minutos para mayor precisión:

```
Expresión cron: cron(0,30 * * * ? *)
```

---

## Configuración de Tags

Añade las siguientes tags a tus instancias EC2:

| Tag | Valor | Descripción |
|-----|-------|-------------|
| `AutoSchedule` | `enabled` / `disabled` | Activa o desactiva el control automático |
| `AutoScheduleStart` | `HH:MM` o cron | Hora de encendido |
| `AutoScheduleStop` | `HH:MM` o cron | Hora de apagado |
| `AutoScheduleDays` | `1-5`, `*`, `1,3,5` | Días de la semana (1=Lunes, 7=Domingo) |
| `Timezone` | `Europe/Madrid`, etc. | Zona horaria |

### Formato de Días

| Valor | Significado |
|-------|-------------|
| `*` | Todos los días |
| `1-5` | Lunes a Viernes |
| `6-7` | Sábado y Domingo |
| `1,3,5` | Lunes, Miércoles, Viernes |

---

## Ejemplos

### Horario de Oficina (08:00-18:00, L-V, Madrid)

```
AutoSchedule:      enabled
AutoScheduleStart: 08:00
AutoScheduleStop:  18:00
AutoScheduleDays:  1-5
Timezone:          Europe/Madrid
```

### Servidor de Desarrollo (09:00-20:00, todos los días)

```
AutoSchedule:      enabled
AutoScheduleStart: 09:00
AutoScheduleStop:  20:00
AutoScheduleDays:  *
Timezone:          UTC
```

### Usando expresión cron completa

Para iniciar a las 8:00 los días laborables:
```
AutoScheduleStart: 0 8 * * 1-5
```

### Configuración Legacy (compatible con versión anterior)

```
startInstance: 0 8 * * 1-5
stopInstance:  0 18 * * 1-5
```

---

## Configuración de Lambda

### Timeout

Recomendado: **30 segundos** (o más si tienes muchas instancias)

### Memoria

Recomendado: **128 MB** (suficiente para la mayoría de casos)

### Variables de Entorno

| Variable | Valor por defecto | Descripción |
|----------|------------------|-------------|
| `DEBUG` | `false` | Activa logs detallados |
| `DEFAULT_TIMEZONE` | `UTC` | Zona horaria por defecto |

---

## Variables de Entorno

Configura en la función Lambda:

```
DEBUG=true                        # Para ver logs detallados
DEFAULT_TIMEZONE=Europe/Madrid    # Zona horaria por defecto
```

---

## Compatibilidad

### Tags Legacy Soportadas

El script mantiene compatibilidad con las tags originales:

- `startInstance`: Expresión cron para iniciar
- `stopInstance`: Expresión cron para detener

Estas tags se detectan automáticamente y funcionan sin necesidad de `AutoSchedule: enabled`.

---

## Ejemplo de Log

```
============================================================
EC2 Auto Start/Stop - Iniciando ejecución
============================================================
🟢 Iniciando instancia: mi-servidor-dev (i-0123456789abcdef0)
🔴 Deteniendo instancia: mi-servidor-test (i-0987654321fedcba0)
----------------------------------------
Instancias totales: 5
Instancias con schedule: 2
Instancias iniciadas: i-0123456789abcdef0
Instancias detenidas: i-0987654321fedcba0
Tiempo de ejecución: 1.23s
============================================================
```

---

## Licencia

Este proyecto está bajo la licencia MIT - ver el archivo [LICENSE](LICENSE) para más detalles.

---

## Contribuciones

Las contribuciones son bienvenidas. Por favor, abre un issue o pull request para sugerencias o mejoras.