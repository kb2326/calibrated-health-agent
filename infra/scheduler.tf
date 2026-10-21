# Cloud Scheduler -> Cloud Run Admin API (jobs:run). Google APIs need an OAuth
# access token, not OIDC. 2 of the 3 free scheduler jobs (per billing account).
locals {
  run_uri = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.sync.name}:run"

  schedules = {
    sync-hourly  = "0 5-12 * * *"
    sync-evening = "30 22 * * *"
  }
}

resource "google_cloud_scheduler_job" "sync" {
  for_each  = local.schedules
  name      = each.key
  region    = var.region
  schedule  = each.value
  time_zone = var.timezone

  attempt_deadline = "180s"

  http_target {
    http_method = "POST"
    uri         = local.run_uri
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode("{}")

    oauth_token {
      service_account_email = google_service_account.scheduler_invoker.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.invoker]
}
