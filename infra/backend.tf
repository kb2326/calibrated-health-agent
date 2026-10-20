# State bucket is created once by bootstrap.sh (versioned).
terraform {
  backend "gcs" {
    bucket = "artful-timing-506108-n8-tfstate"
    prefix = "calibrated-health-agent"
  }
}
