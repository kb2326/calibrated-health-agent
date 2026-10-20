#!/usr/bin/env bash
# One-time: create the versioned Terraform state bucket. NOT run by CI.
set -euo pipefail
PROJECT="${PROJECT:-artful-timing-506108-n8}"
BUCKET="${PROJECT}-tfstate"

if gcloud storage buckets describe "gs://${BUCKET}" --project "${PROJECT}" >/dev/null 2>&1; then
  echo "state bucket gs://${BUCKET} already exists"
  exit 0
fi
gcloud storage buckets create "gs://${BUCKET}" \
  --project "${PROJECT}" --location us-central1 \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update "gs://${BUCKET}" --versioning
echo "created gs://${BUCKET}"
