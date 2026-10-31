"""Cloud mode: only the owner's IAP identity gets through; health.db comes from the bucket."""
from __future__ import annotations

import pytest
from agent_fakes import FakeLlm, text
from fastapi.testclient import TestClient
from health_core.settings import Settings
from health_web import app as app_mod
from health_web.app import create_app
from test_web_agent import fixture_db  # noqa: F401

OWNER = "owner@example.com"
IAP = "X-Goog-Authenticated-User-Email"


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    s = Settings.model_validate({"web_owner_email": OWNER, "db_bucket": None, "data_dir": tmp_path})
    monkeypatch.setattr(app_mod, "get_settings", lambda: s)
    return TestClient(create_app("cloud", model=FakeLlm([text("x")]), static_dir=tmp_path / "none"),
                      base_url="https://cha-web-abc.a.run.app")


def test_owner_through_iap_is_let_in(cloud):
    r = cloud.get("/api/health", headers={IAP: f"accounts.google.com:{OWNER}"})
    assert r.status_code == 200 and r.json()["mode"] == "cloud"


@pytest.mark.parametrize("header", [None, "accounts.google.com:someone@else.com", OWNER + ".evil.com"])
def test_anyone_else_is_refused(cloud, header):
    headers = {IAP: header} if header else {}
    assert cloud.get("/api/health", headers=headers).status_code == 403


def test_cloud_mode_refuses_to_start_without_an_owner(monkeypatch, tmp_path):
    monkeypatch.setattr(app_mod, "get_settings", lambda: Settings.model_validate({"web_owner_email": None}))
    with pytest.raises(ValueError, match="owner"):
        create_app("cloud", model=FakeLlm([text("x")]), static_dir=tmp_path)


def test_health_db_refreshes_from_the_bucket_when_it_changed(monkeypatch, tmp_path):
    from health_data import store

    calls = []
    monkeypatch.setattr(store, "remote_generation", lambda b, o, **k: 7)
    monkeypatch.setattr(store, "recorded_generation", lambda gen_path=None: 6)
    monkeypatch.setattr(store, "pull_db", lambda b, o, d, **k: calls.append((b, o)) or 7)
    s = Settings.model_validate({"db_bucket": "bkt", "data_dir": tmp_path})
    app_mod.refresh_health_db(s)
    assert calls == [("bkt", "health.db")]
    monkeypatch.setattr(store, "recorded_generation", lambda gen_path=None: 7)
    app_mod.refresh_health_db(s)
    assert len(calls) == 1  # unchanged: no download
