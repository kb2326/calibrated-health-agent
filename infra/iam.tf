resource "google_service_account" "sync_job" {
  account_id   = "sync-job"
  display_name = "Daily sync Cloud Run job"
  depends_on   = [google_project_service.enabled]
}

resource "google_service_account" "scheduler_invoker" {
  account_id   = "sync-scheduler"
  display_name = "Cloud Scheduler invoker for the sync job"
  depends_on   = [google_project_service.enabled]
}

resource "google_storage_bucket_iam_member" "sync_job_data" {
  bucket = google_storage_bucket.health_db.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.sync_job.email}"
}

# secretAccessor on exactly the four secrets, nothing project-wide.
resource "google_secret_manager_secret_iam_member" "sync_job_secrets" {
  for_each = {
    oauth_client = google_secret_manager_secret.oauth_client.id
    oauth_token  = google_secret_manager_secret.oauth_token.id
    oauth_forms  = google_secret_manager_secret.oauth_forms_token.id
    ledger_key   = google_secret_manager_secret.ledger_deploy_key.id
  }
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.sync_job.email}"
}

resource "google_cloud_run_v2_job_iam_member" "invoker" {
  name     = google_cloud_run_v2_job.sync.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

# Run query jobs (TimesFM via AI.FORECAST). No dataset access: the query reads only its
# parameters, and every job caps maximum_bytes_billed.
resource "google_project_iam_member" "sync_job_bq_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.sync_job.email}"
}

# Call Gemini on Vertex AI as the job itself (no API key to store).
resource "google_project_iam_member" "sync_job_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.sync_job.email}"
}

# Ledger bucket: create and read objects, never delete or overwrite them.
resource "google_storage_bucket_iam_member" "sync_job_ledger" {
  for_each = toset(["roles/storage.objectCreator", "roles/storage.objectViewer"])
  bucket   = google_storage_bucket.ledger.name
  role     = each.value
  member   = "serviceAccount:${google_service_account.sync_job.email}"
}
