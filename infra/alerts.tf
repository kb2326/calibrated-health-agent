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

  conditions {
    display_name = "scheduler could not invoke the sync job"
    condition_matched_log {
      filter = <<-EOT
        resource.type="cloud_scheduler_job"
        resource.labels.job_id=("sync-hourly" OR "sync-evening")
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

# Metric-based backstop (log-based and metric-based conditions cannot share a
# policy). Metric run.googleapis.com/job/completed_task_attempt_count is DELTA
# INT64 on cloud_run_job with label result; verified via the Monitoring
# metricDescriptors.get API. Any failed task attempt for job sync alerts.
resource "google_monitoring_alert_policy" "sync_task_failed" {
  display_name = "sync job task attempt failed (metric)"
  combiner     = "OR"

  conditions {
    display_name = "completed_task_attempt_count result=failed > 0"
    condition_threshold {
      filter = join(" AND ", [
        "resource.type=\"cloud_run_job\"",
        "resource.labels.job_name=\"sync\"",
        "metric.type=\"run.googleapis.com/job/completed_task_attempt_count\"",
        "metric.labels.result=\"failed\"",
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close = "86400s"
  }

  notification_channels = [google_monitoring_notification_channel.owner_email.id]
  depends_on            = [google_project_service.enabled]
}
