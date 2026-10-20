# GitHub Actions deploy identity, as in w_notes: no long-lived AWS key in the
# repo. The workflow trades a short-lived GitHub OIDC token for this role, and
# only workflows running on main in this one repo may.
#
# The OIDC provider itself is one per account and w_notes already created it,
# so it is looked up here, not managed.

locals {
  github_deploy_enabled = var.github_deploy_repo != ""
}

data "aws_iam_openid_connect_provider" "github" {
  count = local.github_deploy_enabled ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "github_assume" {
  count = local.github_deploy_enabled ? 1 : 0

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github[0].arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_deploy_repo}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  count              = local.github_deploy_enabled ? 1 : 0
  name               = "${local.name}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume[0].json
}

# Push to this ECR repo, register a revision of this task family, roll this
# service. Nothing of w_notes'.
data "aws_iam_policy_document" "github_deploy" {
  count = local.github_deploy_enabled ? 1 : 0

  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:DescribeImages",
    ]
    resources = [aws_ecr_repository.api.arn]
  }

  statement {
    sid       = "EcsDeploy"
    actions   = ["ecs:UpdateService", "ecs:DescribeServices"]
    resources = [aws_ecs_service.api.id]
  }

  # Neither takes a resource ARN that exists before the call.
  statement {
    sid       = "EcsTaskDefinitions"
    actions   = ["ecs:RegisterTaskDefinition", "ecs:DescribeTaskDefinition"]
    resources = ["*"]
  }

  statement {
    sid       = "PassTaskRoles"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.execution.arn, aws_iam_role.task.arn]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  count  = local.github_deploy_enabled ? 1 : 0
  name   = "${local.name}-github-deploy"
  role   = aws_iam_role.github_deploy[0].id
  policy = data.aws_iam_policy_document.github_deploy[0].json
}
