# The web app (Phase 5): Cloud Run behind Cloud Run's built-in IAP, owner-only.
# Scales to zero; one instance at most. Reads health.db, writes only agent.db.

variable "web_image" {
  type        = string
  description = "Artifact Registry image for the web app (apps/webservice/Dockerfile)"
}

resource "google_service_account" "web" {
  account_id   = "cha-web"
  display_name = "Calibrated Health Agent web app"
}

# Read every object in the data bucket (health.db, agent.db)...
resource "google_storage_bucket_iam_member" "web_read" {
  bucket = google_storage_bucket.health_db.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.web.email}"
}

# ...and write only agent.db (the shared chat state). health.db stays the job's alone.
resource "google_storage_bucket_iam_member" "web_agent_db" {
  bucket = google_storage_bucket.health_db.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.web.email}"
  condition {
    title      = "agent-db-only"
    expression = "resource.name == \"projects/_/buckets/${google_storage_bucket.health_db.name}/objects/agent.db\""
  }
}

resource "google_project_iam_member" "web_roles" {
  for_each = toset(["roles/aiplatform.user", "roles/cloudtrace.agent", "roles/telemetry.tracesWriter"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.web.email}"
}

resource "google_cloud_run_v2_service" "web" {
  provider            = google-beta
  name                = "cha-web"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"
  launch_stage        = "BETA"
  iap_enabled         = true # Google sign-in in front of every request

  template {
    service_account                  = google_service_account.web.email
    timeout                          = "600s" # a long streamed answer
    max_instance_request_concurrency = 10
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image = var.web_image
      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle = true
      }
      env {
        name  = "CHA_DB_BUCKET"
        value = google_storage_bucket.health_db.name
      }
      env {
        name  = "CHA_WEB_OWNER_EMAIL"
        value = var.owner_email
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
        name  = "CHA_TRACING"
        value = "cloud"
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "true"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = "global"
      }
    }
  }

  depends_on = [google_project_service.enabled]
}

# The IAP service agent invokes the service on the signed-in owner's behalf.
resource "google_project_service_identity" "iap" {
  provider = google-beta
  project  = var.project_id
  service  = "iap.googleapis.com"
}

resource "google_cloud_run_v2_service_iam_member" "iap_invoker" {
  provider = google-beta
  name     = google_cloud_run_v2_service.web.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_project_service_identity.iap.email}"
}

# Only the owner's Google account may pass IAP.
resource "google_iap_web_cloud_run_service_iam_member" "owner" {
  provider               = google-beta
  project                = var.project_id
  location               = var.region
  cloud_run_service_name = google_cloud_run_v2_service.web.name
  role                   = "roles/iap.httpsResourceAccessor"
  member                 = "user:${var.owner_email}"
}

output "web_url" {
  value = google_cloud_run_v2_service.web.uri
}
