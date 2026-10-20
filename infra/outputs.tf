output "data_bucket" {
  value = google_storage_bucket.health_db.name
}

output "image_repo" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.cha.repository_id}"
}

output "job_service_account" {
  value = google_service_account.sync_job.email
}
