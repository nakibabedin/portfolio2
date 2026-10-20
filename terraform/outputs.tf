output "api_url" {
  description = "Public API base URL."
  value       = "https://${local.api_fqdn}"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "ecs_cluster" {
  value = data.aws_ecs_cluster.shared.cluster_name
}

output "ecs_service" {
  value = aws_ecs_service.api.name
}

output "github_deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE secret in GitHub."
  value       = local.github_deploy_enabled ? aws_iam_role.github_deploy[0].arn : null
}

# Everything `aws ecs run-task` needs for the migration, as one JSON blob so a
# script can read it; see README.md, "Migrating from Railway".
output "migrate_run_config" {
  value = local.migration_enabled ? jsonencode({
    cluster        = data.aws_ecs_cluster.shared.cluster_name
    taskDefinition = aws_ecs_task_definition.migrate[0].family
    subnets        = data.aws_subnets.public.ids
    securityGroups = [aws_security_group.ecs.id, data.aws_security_group.db_client.id]
    logGroup       = aws_cloudwatch_log_group.api.name
  }) : null
}
