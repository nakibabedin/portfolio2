# Fill the ones without defaults in terraform.tfvars, and the secrets in
# secrets.auto.tfvars.json (see scripts/env_to_tfvars.py). Both are gitignored.

variable "project" {
  type        = string
  default     = "portfolio"
  description = "Name prefix applied to resources and tags."
}

variable "region" {
  type    = string
  default = "us-east-1"
}

# ---- Shared infrastructure, owned by the w_notes stack ----
#
# Looked up by name, never managed here. See shared.tf.

variable "shared_prefix" {
  type        = string
  default     = "wnotes"
  description = "Name prefix of the stack that owns the VPC, cluster and RDS instance."
}

# ---- DNS (Cloudflare) ----

variable "domain_name" {
  type    = string
  default = "rileydrcelik.com"
}

variable "api_subdomain" {
  type    = string
  default = "api"
}

variable "cloudflare_zone_id" {
  type        = string
  description = "Cloudflare Zone ID for domain_name."
}

variable "cloudflare_account_id" {
  type        = string
  description = "Cloudflare Account ID. Required to create the Tunnel."
}

variable "cloudflare_api_token" {
  type        = string
  sensitive   = true
  description = "Needs Zone:DNS:Edit on domain_name and Account:Cloudflare Tunnel:Edit."
}

# ---- Compute ----

variable "container_image" {
  type        = string
  default     = ""
  description = "Image the ECS task runs. Empty => this stack's ECR repo at :latest."
}

# Must stay 1. The live audio relay keeps its segments in process memory
# (backend/app/lib/live_relay.py); a second task would have none of them.
variable "desired_count" {
  type    = number
  default = 1
}

# Task-level totals shared by the api and cloudflared containers. 1 GB rather
# than 512 MB because an upload is decoded in full by Pillow before it is
# resized, and a large photo alone can take a few hundred MB.
variable "task_cpu" {
  type    = number
  default = 256
}

variable "task_memory" {
  type    = number
  default = 1024
}

# ---- Database ----

variable "db_name" {
  type        = string
  default     = "portfolio"
  description = "Database (and its owning role) created on the shared RDS instance."
}

# ---- App configuration ----

variable "app_secrets" {
  type        = map(string)
  sensitive   = true
  default     = {}
  description = <<-EOT
    Every env var the app reads, except DATABASE_URL (built here) and the AWS
    keys (the task role replaces them). Each becomes an SSM SecureString and is
    injected into the container under the same name. Generate from a Railway
    export with scripts/env_to_tfvars.py.
  EOT
}

variable "images_bucket" {
  type        = string
  default     = "portfoliowebsite-images"
  description = "Existing S3 bucket the app uploads to. Not managed here; the task role is granted access."
}

# ---- Migration from Railway (see migrate.tf) ----

variable "migration_source_database_url" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Public connection string of the Railway Postgres being copied. Empty => no migration task. Clear it once the move is done."
}

# ---- CI/CD ----

variable "github_deploy_repo" {
  type        = string
  default     = "rileydrcelik/portfolio2"
  description = "owner/name of the repo allowed to deploy via OIDC. Empty => deploys stay manual."
}
