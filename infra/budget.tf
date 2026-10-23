data "google_project" "this" {
  project_id = var.project_id
  depends_on = [google_project_service.enabled]
}

resource "google_monitoring_notification_channel" "owner_email" {
  display_name = "calibrated-health-agent owner email"
  type         = "email"
  labels = {
    email_address = var.owner_email
  }
  depends_on = [google_project_service.enabled]
}

resource "google_billing_budget" "this" {
  billing_account = var.billing_account
  display_name    = "calibrated-health-agent"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = "1"
    }
  }

  # Owner cap: under $1/month. Email at $0.25 and $0.50 actual, and as soon as the
  # month's forecast reaches $1, so a cost leak is caught before the bill lands.
  threshold_rules {
    threshold_percent = 0.25
  }
  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.owner_email.id]
    disable_default_iam_recipients   = false
  }

  depends_on = [google_project_service.enabled]
}
