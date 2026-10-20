resource "google_artifact_registry_repository" "cha" {
  repository_id = "cha"
  location      = var.region
  format        = "DOCKER"
  description   = "calibrated-health-agent job images"

  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "keep-3-most-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 3
    }
  }

  cleanup_policies {
    id     = "delete-the-rest"
    action = "DELETE"
    condition {
      tag_state = "ANY"
    }
  }

  depends_on = [google_project_service.enabled]
}
