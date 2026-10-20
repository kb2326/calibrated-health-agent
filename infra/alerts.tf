# Fires on any ERROR+ log line from the sync job. That covers the Cloud Run
# system log emitted when an execution fails as well as the job's own JSON
# severity=ERROR lines (steps pull/migrate/sync/journal/push).
resource "google_monitoring_alert_policy" "sync_failure" {
  display_name = "sync job failure"
  combiner     = "OR"

  conditions {
    display_name = "sync job execution failed or logged ERROR"
    condition_matched_log {
      filter = <<-EOT
        resource.type="cloud_run_job"
        resource.labels.job_name="sync"
        severity>=ERROR
      EOT
    }
  }

  alert_strategy {
    notification_rate_limit {
      period = "3600s"
    }
    auto_close = "86400s"
  }

  notification_channels = [google_monitoring_notification_channel.owner_email.id]
  depends_on            = [google_project_service.enabled]
}
