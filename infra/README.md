# infra: free-tier GCP slice for the daily sync

Project `artful-timing-506108-n8`, region `us-central1`. Cloud Run **job** only
(no always-on service, no load balancer, no VPC, no Cloud Build). Expected cost:
about $0.03/month, far under the $5/month budget (see table).

## What it creates (29 resources)

8 project services (+ cloudresourcemanager, needed to read the project number),
GCS data bucket `…-health-db`, secrets `oauth-client` / `oauth-token` (Health) /
`oauth-forms-token` (Forms; a separate token, because the Health API rejects
access tokens that carry non-Health scopes) (containers only), Artifact Registry repo `cha`, service accounts `sync-job` and
`sync-scheduler`, Cloud Run job `sync` (2Gi, 1 vCPU, 15 min, 1 retry), Cloud
Scheduler `sync-hourly` (`0 5-12 * * *`) and `sync-evening` (`30 22 * * *`),
`Asia/Kolkata`, calling the Run Admin API with an OAuth token, a $5 budget
(alerts at $2 and $4), an email channel and three alert policies: a log
alert on `severity>=ERROR` from the `sync` job, a log alert on `severity>=ERROR`
from the two scheduler jobs, and a metric alert on
`run.googleapis.com/job/completed_task_attempt_count` with `result="failed"`.

Design rationale: [docs/cloud-design.md](../docs/cloud-design.md).

| Resource | Monthly cost |
|---|---|
| Cloud Run job | $0 (a few minutes/day of 1 vCPU / 2 GiB is inside the free tier) |
| Cloud Scheduler | $0 (2 of 3 free jobs per billing account) |
| Secret Manager | $0 (3 secrets, few versions/accesses; free tier 6 versions) |
| GCS data bucket | $0 (tens of MB, under 5 GB free) |
| Artifact Registry | ~$0.03 (3 images x ~260 MB = ~0.78 GB; 0.5 GB is free, ~0.28 GB x $0.10/GB) |
| Budgets, Monitoring alert, email channel | $0 |

## Auth

    export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token)

The identity needs project owner/editor plus Billing Account Costs Manager on
`01DA8F-C0DAA3-A37763`. The provider uses `user_project_override = true` and
`billing_project = "artful-timing-506108-n8"`.

Local `infra/terraform.tfvars` (gitignored, never commit) holds
`journal_form_id` (from `config/journal_form.json`) and `job_image`.

## Offline checks (also run in CI)

    terraform fmt -check -recursive
    terraform init -backend=false && terraform validate

## Apply order (needs owner approval)

1. `infra/bootstrap.sh` creates the versioned state bucket
   `artful-timing-506108-n8-tfstate` (once).
2. `terraform init -migrate-state` (backend.tf points at that bucket).
3. Targeted apply so the repo exists before the image:
   `terraform apply -target=google_project_service.enabled -target=google_artifact_registry_repository.cha`
4. Build and push (no Cloud Build):
   `gcloud auth configure-docker us-central1-docker.pkg.dev`, then
   `docker build -f apps/jobs/Dockerfile -t us-central1-docker.pkg.dev/artful-timing-506108-n8/cha/sync-job:<git-sha> .`
   and `docker push` the same tag. Set `job_image` in the gitignored `infra/terraform.tfvars`.
5. Full `terraform plan -out tfplan` then `terraform apply tfplan`.
6. Put secret values (owner, locally; never print tokens). Add `forms.responses.readonly`
   and `forms.body.readonly` to the OAuth consent screen scopes first, then:
   `uv run cha-data auth login` (Health scopes only),
   `uv run cha-data auth login-forms` (Forms scopes only), and
   `CHA_TOKEN_SECRET=oauth-token CHA_CLIENT_SECRET_SECRET=oauth-client CHA_FORMS_TOKEN_SECRET=oauth-forms-token uv run cha-data auth push-secret`
   (pushes `oauth-client`, `oauth-token`, `oauth-forms-token`; keeps the previous version
   disabled for rollback and destroys older ones).
7. Seed the bucket and run once (owner, locally):
   `CHA_DB_BUCKET=artful-timing-506108-n8-health-db uv run cha-data db push`, then
   `gcloud run jobs execute sync --region us-central1 --wait`. A green first run
   logs pull, migrate, sync, journal import and push in that order (push may log
   "skipped (no data changed)" when nothing new arrived).
8. Alert test (no drift): the job's secret names are env vars, so override
   them for one execution only; this does not touch the job template or
   Terraform state:
   `gcloud run jobs execute sync --region us-central1 --args=--dry-run --update-env-vars CHA_TOKEN_SECRET=does-not-exist`
   NOTE: `--update-env-vars` on `jobs execute` applies to that execution only
   (override); if gcloud instead reports it modified the job, run
   `terraform apply` to restore the template. Confirm the alert email arrives
   (log policy is rate limited to one per hour).

## Rollback (needs owner approval)

**Image only, same schema.** Artifact Registry keeps the 3 most recent images. Set
`job_image` in `infra/terraform.tfvars` to the previous tag, then `terraform plan -out
tfplan` and `terraform apply tfplan`.

**Across a schema change.** An older image refuses a database with a newer schema
(`SchemaTooNewError`, logged as an ERROR, so the alert fires) and never writes to it.
To go back to an older image after a migration, restore the database too, from a
noncurrent bucket version (kept 14 days):

1. Pause both schedulers so no run writes mid-restore:
   `gcloud scheduler jobs pause sync-hourly --location us-central1` (same for `sync-evening`).
2. List versions and pick the last generation written by the older schema:
   `gcloud storage ls -a gs://artful-timing-506108-n8-health-db/health.db`.
3. Make that version current again (a copy creates a new generation; nothing is deleted):
   `gcloud storage cp gs://artful-timing-506108-n8-health-db/health.db#<generation> gs://artful-timing-506108-n8-health-db/health.db`.
4. Roll the image back as above, then run once and check the logs:
   `gcloud run jobs execute sync --region us-central1 --wait`.
5. Resume both schedulers (`gcloud scheduler jobs resume ...`).

Nothing is lost by the restore. Each type's restored cursor is older, so the next sync
re-fetches from that day, and the journal import re-reads every Form response and skips
the ones already stored. The heartbeat object (`health.db.heartbeat.json`) needs no
restore; the next run overwrites it.

## Plan-only review without the real backend

Add a temporary `infra/backend_override.tf` containing
`terraform { backend "local" {} }` (gitignored), `terraform init`, `terraform
plan -out tfplan`, then delete the override and plan files.
