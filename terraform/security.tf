# The task's own firewall: no inbound at all (public traffic arrives through the
# Cloudflare Tunnel, which the task dials out to), egress anywhere.
#
# Postgres access is not granted here. The task also carries the shared
# db-client group (shared.tf), which the RDS instance's own group admits.

resource "aws_security_group" "ecs" {
  name        = "${local.name}-ecs"
  description = "Portfolio API; no inbound, egress only (ingress via Cloudflare Tunnel)"
  vpc_id      = data.aws_vpc.shared.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-ecs" }
}
