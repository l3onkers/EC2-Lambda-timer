# Terraform configuration for EC2 Auto Start/Stop Lambda
# =========================================================
# Este archivo Terraform despliega la función Lambda con todos sus recursos

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  required_version = ">= 1.0"
}

provider "aws" {
  region = var.aws_region
}

# Variables
variable "aws_region" {
  description = "Región de AWS donde desplegar"
  type        = string
  default     = "eu-west-1"
}

variable "function_name" {
  description = "Nombre de la función Lambda"
  type        = string
  default     = "ec2-auto-start-stop"
}

variable "schedule_expression" {
  description = "Expresión cron para EventBridge (cada hora por defecto)"
  type        = string
  default     = "cron(0 * * * ? *)"
}

variable "default_timezone" {
  description = "Zona horaria por defecto"
  type        = string
  default     = "Europe/Madrid"
}

variable "debug_mode" {
  description = "Activa el modo debug"
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags a aplicar a los recursos"
  type        = map(string)
  default = {
    Project     = "EC2-Auto-StartStop"
    ManagedBy   = "Terraform"
  }
}

# IAM Role para Lambda
resource "aws_iam_role" "lambda_role" {
  name = "${var.function_name}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

# IAM Policy para EC2 y CloudWatch Logs
resource "aws_iam_role_policy" "lambda_policy" {
  name = "${var.function_name}-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EC2InstanceControl"
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances",
          "ec2:DescribeTags",
          "ec2:StartInstances",
          "ec2:StopInstances"
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

# Archivo ZIP para Lambda
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/EC2StopStart.py"
  output_path = "${path.module}/lambda_function.zip"
}

# Función Lambda
resource "aws_lambda_function" "ec2_scheduler" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = var.function_name
  role             = aws_iam_role.lambda_role.arn
  handler          = "EC2StopStart.lambda_handler"
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  runtime          = "python3.11"
  timeout          = 30
  memory_size      = 128

  environment {
    variables = {
      DEBUG            = tostring(var.debug_mode)
      DEFAULT_TIMEZONE = var.default_timezone
    }
  }

  tags = var.tags
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.ec2_scheduler.function_name}"
  retention_in_days = 14

  tags = var.tags
}

# EventBridge Rule (para ejecutar cada hora)
resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "${var.function_name}-schedule"
  description         = "Ejecuta la Lambda de EC2 Start/Stop periódicamente"
  schedule_expression = var.schedule_expression

  tags = var.tags
}

# EventBridge Target
resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.schedule.name
  target_id = "ec2-scheduler-lambda"
  arn       = aws_lambda_function.ec2_scheduler.arn
}

# Permiso para que EventBridge invoque Lambda
resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ec2_scheduler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
}

# Outputs
output "lambda_function_name" {
  description = "Nombre de la función Lambda"
  value       = aws_lambda_function.ec2_scheduler.function_name
}

output "lambda_function_arn" {
  description = "ARN de la función Lambda"
  value       = aws_lambda_function.ec2_scheduler.arn
}

output "eventbridge_rule_name" {
  description = "Nombre de la regla de EventBridge"
  value       = aws_cloudwatch_event_rule.schedule.name
}

output "cloudwatch_log_group" {
  description = "Grupo de logs de CloudWatch"
  value       = aws_cloudwatch_log_group.lambda_logs.name
}
