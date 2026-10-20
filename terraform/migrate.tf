# One-off task that copies the Railway database into this stack's database on
# the shared RDS instance (script: migrate/migrate.sh). The RDS instance is only
# reachable from inside the VPC, so the copy has to run here rather than from a
# laptop. Run with the command in `terraform output migrate_command`.
#
# Exists only while migration_source_database_url is set. Clear it after the
# cutover and apply: the task, its role and the Railway URL all go away.

resource "aws_ssm_parameter" "migration_source" {
  count = local.migration_enabled ? 1 : 0
  name  = "/${local.name}/migrate/source-database-url"
  type  = "SecureString"
  value = var.migration_source_database_url
}

resource "aws_iam_role" "migrate_execution" {
  count              = local.migration_enabled ? 1 : 0
  name               = "${local.name}-migrate-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "migrate_execution_managed" {
  count      = local.migration_enabled ? 1 : 0
  role       = aws_iam_role.migrate_execution[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The RDS master credentials are w_notes' parameter, named by ARN rather than
# read through a data source, so their value never enters this stack's state.
# Only this short-lived task can read them; the API task cannot.
resource "aws_iam_role_policy" "migrate_secrets" {
  count = local.migration_enabled ? 1 : 0
  name  = "${local.name}-migrate-read-secrets"
  role  = aws_iam_role.migrate_execution[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["ssm:GetParameters"]
      Resource = [
        aws_ssm_parameter.migration_source[0].arn,
        aws_ssm_parameter.db_password.arn,
        "${local.ssm_arn_prefix}/${var.shared_prefix}/database-url",
      ]
    }]
  })
}

resource "aws_ecs_task_definition" "migrate" {
  count                    = local.migration_enabled ? 1 : 0
  family                   = "${local.name}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.migrate_execution[0].arn

  container_definitions = jsonencode([{
    name = "migrate"
    # pg_dump must be at least as new as the server it dumps; 18 covers any
    # Railway Postgres, and its output restores into the RDS 16 instance.
    image     = "postgres:18"
    essential = true
    command   = ["bash", "-c", file("${path.module}/migrate/migrate.sh")]

    environment = [
      { name = "DB_NAME", value = var.db_name },
      { name = "DB_HOST", value = data.aws_db_instance.shared.address },
      { name = "MODE", value = "rehearse" },
    ]

    secrets = [
      { name = "SOURCE_URL", valueFrom = aws_ssm_parameter.migration_source[0].arn },
      { name = "MASTER_URL", valueFrom = "${local.ssm_arn_prefix}/${var.shared_prefix}/database-url" },
      { name = "DB_PASSWORD", valueFrom = aws_ssm_parameter.db_password.arn },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "migrate"
      }
    }
  }])
}
