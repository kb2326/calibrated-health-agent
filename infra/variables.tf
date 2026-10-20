variable "project_id" {
  type    = string
  default = "artful-timing-506108-n8"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "billing_account" {
  type    = string
  default = "01DA8F-C0DAA3-A37763"
}

variable "owner_email" {
  type    = string
  default = "karthickbalaje01@gmail.com"
}

variable "timezone" {
  type    = string
  default = "Asia/Kolkata"
}

variable "journal_form_id" {
  description = "Google Form ID of the journal. Never committed; set in the gitignored terraform.tfvars."
  type        = string
}

variable "job_image" {
  description = "Full image URI, e.g. us-central1-docker.pkg.dev/<project>/cha/sync-job:<git-sha>."
  type        = string
}
