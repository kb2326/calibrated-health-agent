# Ledger mirror: every chain entry as one object. A 365-day retention policy blocks
# deletes and overwrites; it is deliberately NOT locked yet (locking is permanent and is
# the owner's Phase 8 step). No versioning: objects are written once.
resource "google_storage_bucket" "ledger" {
  name                        = "${var.project_id}-ledger"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  retention_policy {
    retention_period = 31536000
    is_locked        = false
  }
}

resource "google_storage_bucket" "health_db" {
  name                        = "${var.project_id}-health-db"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  # Restore window by age, not by count: the job can push several times a day, so a
  # count limit (was 10 versions) kept only about a day of history. A noncurrent version
  # is deleted 14 days after it was superseded. At ~12 MB and <= 9 pushes/day that is
  # about 1.5 GB of noncurrent data, inside the 5 GB free tier (the job also skips pushes
  # that change no data).
  lifecycle_rule {
    condition {
      days_since_noncurrent_time = 14
      with_state                 = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }
}
