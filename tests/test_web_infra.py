"""The web service's Terraform keeps its security properties (Phase 5 Task 13)."""
from __future__ import annotations

import re
from pathlib import Path

TF = (Path(__file__).resolve().parents[1] / "infra" / "web.tf").read_text(encoding="utf-8")


def test_iap_on_and_owner_only():
    assert re.search(r"iap_enabled\s*=\s*true", TF)
    accessors = re.findall(r'role\s*=\s*"roles/iap.httpsResourceAccessor"\s*\n\s*member\s*=\s*"([^"]+)"', TF)
    assert accessors == ["user:${var.owner_email}"]
    assert "allUsers" not in TF and "allAuthenticatedUsers" not in TF


def test_scales_to_zero_with_one_instance_and_long_streams():
    assert re.search(r"min_instance_count\s*=\s*0", TF)
    assert re.search(r"max_instance_count\s*=\s*1", TF)
    assert re.search(r'timeout\s*=\s*"600s"', TF)


def test_web_writes_only_agent_db():
    admin = TF.split('resource "google_storage_bucket_iam_member" "web_agent_db"')[1].split("resource ")[0]
    assert "roles/storage.objectUser" in admin and "objects/agent.db" in admin
    read = TF.split('resource "google_storage_bucket_iam_member" "web_read"')[1].split("resource ")[0]
    assert "roles/storage.objectViewer" in read


def test_owner_email_reaches_the_app_as_its_second_lock():
    assert re.search(r'name\s*=\s*"CHA_WEB_OWNER_EMAIL"\s*\n\s*value\s*=\s*var.owner_email', TF)
