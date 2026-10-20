# Two roles, as in w_notes: the execution role is what ECS itself uses to pull
# the image, write logs and fetch secrets; the task role is what the app's own
# code runs as.

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# ---- Execution role ----

resource "aws_iam_role" "execution" {
  name               = "${local.name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Exactly the parameters the API task injects. Not the migration's (migrate.tf
# has its own role for those), and nothing of w_notes'.
data "aws_iam_policy_document" "read_secrets" {
  statement {
    actions = ["ssm:GetParameters"]
    resources = concat(
      [
        aws_ssm_parameter.database_url.arn,
        aws_ssm_parameter.tunnel_token.arn,
      ],
      [for p in aws_ssm_parameter.app : p.arn],
    )
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "${local.name}-read-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.read_secrets.json
}

# ---- Task (application) role ----
#
# Replaces the AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY pair the app used on
# Railway. app/lib/s3.py passes those to boto3 straight from the environment;
# unset, they are None, and boto3 falls back to this role.

resource "aws_iam_role" "task" {
  name               = "${local.name}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# What app/lib/s3.py does: put_object on upload, delete_object when a post's
# media is replaced or removed. Get for good measure (reads of its own objects).
data "aws_iam_policy_document" "task_s3" {
  statement {
    actions   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
    resources = ["arn:aws:s3:::${var.images_bucket}/*"]
  }
}

resource "aws_iam_role_policy" "task_s3" {
  name   = "${local.name}-images-s3"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_s3.json
}
