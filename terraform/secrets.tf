# Runtime secrets, as SSM Parameter Store SecureStrings (free, where Secrets
# Manager bills per secret). The task references each by ARN and ECS injects
# the decrypted value as an env var at start.

# The portfolio role's password on the shared RDS instance. Generated, so no
# human ever picks it; URL-safe so it drops cleanly into DATABASE_URL.
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "aws_ssm_parameter" "db_password" {
  name  = "/${local.name}/db-password"
  type  = "SecureString"
  value = random_password.db.result
}

# psycopg2 form (plain postgresql://), which is what app/database.py hands to
# SQLAlchemy.
resource "aws_ssm_parameter" "database_url" {
  name  = "/${local.name}/database-url"
  type  = "SecureString"
  value = "postgresql://${var.db_name}:${random_password.db.result}@${data.aws_db_instance.shared.address}:5432/${var.db_name}"
}

resource "aws_ssm_parameter" "tunnel_token" {
  name  = "/${local.name}/tunnel-token"
  type  = "SecureString"
  value = cloudflare_zero_trust_tunnel_cloudflared.api.tunnel_token
}

# One parameter per app env var. The names aren't secret, so they can key the
# for_each; only the values stay sensitive.
resource "aws_ssm_parameter" "app" {
  for_each = nonsensitive(toset(keys(var.app_secrets)))

  name  = "/${local.name}/env/${each.key}"
  type  = "SecureString"
  value = var.app_secrets[each.key]
  # The standard tier caps a value at 4 KB; a Firebase service account is
  # usually under that, but don't fail the apply if one isn't.
  tier = length(var.app_secrets[each.key]) > 4096 ? "Advanced" : "Standard"
}
