resource "google_cloud_run_v2_job" "sync" {
  name                = "sync"
  location            = var.region
  deletion_protection = false

  template {
    task_count = 1

    template {
      max_retries     = 1
      timeout         = "900s"
      service_account = google_service_account.sync_job.email

      containers {
        image = var.job_image

        resources {
          limits = {
            cpu    = "1"
            memory = "2Gi"
          }
        }

        env {
          name  = "CHA_DB_BUCKET"
          value = google_storage_bucket.health_db.name
        }
        env {
          name  = "CHA_DB_OBJECT"
          value = "health.db"
        }
        env {
          name  = "CHA_TOKEN_SECRET"
          value = google_secret_manager_secret.oauth_token.secret_id
        }
        env {
          name  = "CHA_FORMS_TOKEN_SECRET"
          value = google_secret_manager_secret.oauth_forms_token.secret_id
        }
        env {
          name  = "CHA_CLIENT_SECRET_SECRET"
          value = google_secret_manager_secret.oauth_client.secret_id
        }
        env {
          name  = "CHA_JOURNAL_FORM_ID"
          value = var.journal_form_id
        }
        env {
          name  = "CHA_GCP_PROJECT"
          value = var.project_id
        }
        env {
          name  = "CHA_TIMEZONE"
          value = var.timezone
        }
        env {
          name  = "CHA_LEDGER_BUCKET"
          value = google_storage_bucket.ledger.name
        }
        env {
          name  = "CHA_LEDGER_REPO"
          value = "git@github.com:kb2326/cha-ledger-log.git"
        }
        env {
          name  = "CHA_LEDGER_KEY_SECRET"
          value = google_secret_manager_secret.ledger_deploy_key.secret_id
        }
        env {
          name  = "CHA_ANALYSIS_PLAN_PATH"
          value = "/app/docs/ledger/analysis-plan.md"
        }
      }
    }
  }

  depends_on = [google_project_service.enabled]
}
