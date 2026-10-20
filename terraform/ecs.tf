# The service, in the shared cluster. Two containers per task: the app, and the
# cloudflared sidecar that connects the tunnel.

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name}-api"
  retention_in_days = 30
}

locals {
  container_secrets = concat(
    [{ name = "DATABASE_URL", valueFrom = aws_ssm_parameter.database_url.arn }],
    [for k, p in aws_ssm_parameter.app : { name = k, valueFrom = p.arn }],
  )
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = local.container_image
      essential = true

      portMappings = [{
        containerPort = 8000
        protocol      = "tcp"
      }]

      environment = [
        { name = "AWS_REGION", value = var.region },
      ]

      secrets = local.container_secrets

      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\""]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "api"
        }
      }
    },
    {
      name      = "cloudflared"
      image     = "cloudflare/cloudflared:latest"
      essential = true
      command   = ["tunnel", "--no-autoupdate", "run"]

      secrets = [
        { name = "TUNNEL_TOKEN", valueFrom = aws_ssm_parameter.tunnel_token.arn }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "cloudflared"
        }
      }
    },
  ])
}

resource "aws_ecs_service" "api" {
  name            = "${local.name}-api"
  cluster         = data.aws_ecs_cluster.shared.arn
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.desired_count

  # Spot: ~70% cheaper. A reclaim (2 minutes' notice) means a minute or two of
  # downtime while ECS starts a replacement, and drops a live stream if one is
  # running; the phone reconnects to the new task.
  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 1
  }

  # Never two tasks at once, even mid-deploy: the live relay's segments are in
  # one process's memory, and a second task would answer 404 for them. A deploy
  # stops the old task before starting the new one, so it is a brief outage.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  network_configuration {
    # Public subnets + a public IP for free egress (Stripe, Printify, Aiko,
    # Instagram, Firebase) without a NAT gateway. Nothing reaches the task
    # inbound: its group has no ingress rules.
    subnets          = data.aws_subnets.public.ids
    security_groups  = [aws_security_group.ecs.id, data.aws_security_group.db_client.id]
    assign_public_ip = true
  }

  # Deploys run unattended from CI; a revision that never gets healthy rolls
  # itself back to the previous one.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  lifecycle {
    # CI registers a revision per commit and points the service at it (see
    # .github/workflows/deploy-backend.yml); an apply must not drag it back. An
    # infra-only change here lands on the next deploy, which builds from the
    # family's latest revision.
    ignore_changes = [task_definition]
  }
}
