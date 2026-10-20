# Deliberately NOT cloudbuild (its staging bucket is outside the free tier).
locals {
  services = [
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "billingbudgets.googleapis.com",
    "forms.googleapis.com",
    "iam.googleapis.com",
    "monitoring.googleapis.com",
    "cloudresourcemanager.googleapis.com", # needed to read the project number for the budget filter
  ]
}

resource "google_project_service" "enabled" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}
