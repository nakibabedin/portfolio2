# Portfolio API infrastructure (Terraform)

Runs the FastAPI backend on **ECS Fargate Spot** behind a **Cloudflare Tunnel**
at `api.rileydrcelik.com`, with its own database on the **shared RDS instance**.

```
Cloudflare edge (api.rileydrcelik.com, TLS)
        │  tunnel: the task dials out, nothing inbound
        ▼
ECS task in the shared cluster (public subnet, no inbound rules)
├─ cloudflared sidecar
├─ FastAPI (one uvicorn worker) on :8000
├──> RDS instance shared with w_notes: database + role "portfolio"
├──> S3 portfoliowebsite-images (task role, no access keys)
└──> Stripe, Printify, Aiko, Instagram, Firebase via the internet gateway
```

## What's shared with w_notes, and what isn't

The w_notes stack (`rileydrcelik/w_notes`, `terraform/`) owns the VPC, the ECS
cluster and the RDS instance; `shared.tf` only looks them up. This stack has its
own state file, so an apply here cannot change anything of w_notes'.

| Shared (owned by w_notes) | This stack's own |
|---|---|
| VPC, public subnets | Security group, task + execution roles |
| ECS cluster `wnotes-cluster` | Service, task definition, ECR repo, logs |
| RDS instance `wnotes-db` | Database and role `portfolio`, its password |
| The `wnotes-db-client` group RDS admits | Cloudflare tunnel and DNS record |

Data is fully separate: the `portfolio` role owns the `portfolio` database and
nothing else, and only it (and the master) may connect to it. What the two apps
share is the instance's CPU, 1 GB of memory and connection limit. If w_notes
outgrows that, give this stack its own instance: a new `aws_db_instance` here
and the same migration task run against it.

**Cost:** about $7/month: Fargate Spot ~$3, the task's public IPv4 ~$3.65, logs
and ECR under $1. The database adds nothing until it needs its own instance.

## Files

| File | What it defines |
|---|---|
| `versions.tf` | Provider pins; state in w_notes' bucket under `portfolio/` |
| `shared.tf` | Lookups of the VPC, cluster, RDS instance, db-client group |
| `security.tf` | The task's security group (egress only) |
| `secrets.tf` | DB password, DATABASE_URL, tunnel token, one SSM parameter per app env var |
| `iam.tf` | Execution role (secrets) and task role (S3) |
| `ecs.tf` | Task definition (app + cloudflared) and the Spot service |
| `tunnel.tf` | Cloudflare Tunnel and `api.rileydrcelik.com` |
| `ecr.tf` | Image registry |
| `github_oidc.tf` | The role GitHub Actions deploys as |
| `migrate.tf`, `migrate/` | One-off task that copies the Railway database |

## Setup

1. **Cloudflare token** with *Zone → DNS → Edit* on `rileydrcelik.com` and
   *Account → Cloudflare Tunnel → Edit*. Put it in `secret.auto.tfvars` as
   `cloudflare_api_token = "..."`, or in `TF_VAR_cloudflare_api_token`.
2. `terraform.tfvars` from `terraform.tfvars.example`.
3. **App env vars:** export Railway's variables (service → Variables → Raw
   Editor, copy all) to `railway.env` here, then
   `..\backend\venv\Scripts\python.exe scripts\env_to_tfvars.py railway.env`.
   That writes `secrets.auto.tfvars.json`. Delete `railway.env` afterwards.
4. `terraform init -backend-config=backend.hcl`, `terraform plan`, `terraform apply`.
5. Push the first image (CI can't yet, since the service is what it updates):

   ```bash
   REPO=$(terraform output -raw ecr_repository_url)
   aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO%%/*}"
   docker build -t "$REPO:latest" ../backend && docker push "$REPO:latest"
   aws ecs update-service --cluster wnotes-cluster --service portfolio-api --force-new-deployment
   ```

6. CI deploys: `gh secret set AWS_DEPLOY_ROLE --body "$(terraform output -raw github_deploy_role_arn)"`.
   From then on, any push to `main` touching `backend/` deploys itself (see
   `.github/workflows/deploy-backend.yml`).

## Migrating from Railway

`migrate/migrate.sh`, run as an ECS task inside the VPC (the RDS instance has no
public access). Each run drops and recreates the `portfolio` database, copies
Railway into it in one transaction, then compares every table's row count and
checksum, and every sequence, against the source.

1. Set `migration_source_database_url` (Railway's *public* Postgres URL) and apply.
2. **Rehearse**, as often as you like, with the site still live:
   `scripts/run_migration.sh rehearse`. Mismatches are reported but don't
   fail; tables the site writes to all the time (now playing) may differ.
3. **Cut over:**
   1. Stop the Railway backend service (leave its database alone).
   2. `scripts/run_migration.sh final`. Any mismatch fails it; success marks the
      database `migrated-final`, after which the script refuses to overwrite it.
   3. `aws ecs update-service --cluster wnotes-cluster --service portfolio-api --force-new-deployment`
   4. Point everything at `https://api.rileydrcelik.com`:
      - `frontend/src/lib/api.ts` (`PRODUCTION_API_HOST`), commit, Vercel deploys
      - w_notes: `portfolio_api_base` in its tfvars, apply, redeploy
      - Stripe webhook endpoint → `/api/shop/webhooks/stripe`
      - Printify order webhooks: `python scripts/printify_setup.py webhooks https://api.rileydrcelik.com` (from `backend/`)
      - mariposa's Settings
4. Keep Railway (stopped) for a week as the fallback, then clear
   `migration_source_database_url`, apply, and delete the Railway project.

**Rolling back** before Railway is deleted: start the Railway backend and revert
`api.ts`. Anything written on AWS in between would need copying back by hand.
