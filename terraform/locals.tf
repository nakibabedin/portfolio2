locals {
  name     = var.project
  api_fqdn = "${var.api_subdomain}.${var.domain_name}"

  tags = {
    Project   = var.project
    ManagedBy = "terraform"
  }

  container_image = var.container_image != "" ? var.container_image : "${aws_ecr_repository.api.repository_url}:latest"

  # Whether it is set isn't secret, only its value; count can't take a sensitive bool.
  migration_enabled = nonsensitive(var.migration_source_database_url != "")

  ssm_arn_prefix = "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter"
}
