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

# secretAccessor on exactly the two secrets, nothing project-wide.
resource "google_secret_manager_secret_iam_member" "sync_job_secrets" {
  for_each = {
    oauth_client = google_secret_manager_secret.oauth_client.id
    oauth_token  = google_secret_manager_secret.oauth_token.id
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
