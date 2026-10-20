provider "aws" {
  region = var.region

  default_tags {
    tags = local.tags
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

data "aws_caller_identity" "current" {}
