# Terraform + provider version pins, and the remote state backend.
#
# State lives in the same bucket as w_notes' (it already exists, is versioned and
# private) under its own key, so the two stacks never share a state file or a
# lock: an apply here cannot touch a w_notes resource. Wire it up with:
#
#   terraform init -backend-config=backend.hcl

terraform {
  required_version = ">= 1.10"

  backend "s3" {
    key          = "portfolio/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.40"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
