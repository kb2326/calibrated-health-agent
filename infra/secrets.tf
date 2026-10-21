# Containers only: secret values are added out-of-band (never in state/code).
resource "google_secret_manager_secret" "oauth_client" {
  secret_id = "oauth-client"
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret" "oauth_token" {
  secret_id = "oauth-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}

# Separate token for Forms (the Health API rejects tokens carrying non-Health scopes).
resource "google_secret_manager_secret" "oauth_forms_token" {
  secret_id = "oauth-forms-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}
