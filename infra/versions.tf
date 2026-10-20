terraform {
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

# Auth: export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token)
# user_project_override + billing_project are required for the billing budget
# API (it needs a quota project) and are harmless for the rest.
provider "google" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}
