# Infrastructure this stack runs on but does not own. The w_notes stack
# (rileydrcelik/w_notes, terraform/) creates all of it; here it is only read.
#
#   VPC + public subnets  - free, and each task gets its own network interface
#   ECS cluster           - just a grouping; every task has its own Fargate VM
#   RDS instance          - the one real sharing: this stack gets its own
#                           database and role on it (see db.tf)
#
# Nothing here can change those resources. The flip side: destroying or
# replacing them in the w_notes stack takes this one down too. When a third app
# joins, move them into a `platform` stack that both read from.

data "aws_vpc" "shared" {
  tags = { Name = "${var.shared_prefix}-vpc" }
}

data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.shared.id]
  }
  tags = { Name = "${var.shared_prefix}-public-*" }
}

data "aws_ecs_cluster" "shared" {
  cluster_name = "${var.shared_prefix}-cluster"
}

data "aws_db_instance" "shared" {
  db_instance_identifier = "${var.shared_prefix}-db"
}

# Carrying this group is what lets a task through the RDS firewall.
data "aws_security_group" "db_client" {
  vpc_id = data.aws_vpc.shared.id
  name   = "${var.shared_prefix}-db-client"
}
