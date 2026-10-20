"""Token loading uses the granted scopes; scope gap and refresh failure are surfaced."""
from __future__ import annotations

from datetime import date

import pytest
from fakes import FakeService
from google.auth.exceptions import RefreshError
from health_data import auth, client


class _Creds:
    valid = False
    expired = True
    refresh_token = "r"  # noqa: S105
    scopes = ["https://www.googleapis.com/auth/googlehealth.sleep.readonly"]

    def refresh(self, _request):
        raise RefreshError("invalid_scope")


@pytest.fixture
def token(tmp_path, monkeypatch):
    path = tmp_path / "token.json"
    path.write_text("{}")
    monkeypatch.setattr(auth, "TOKEN_PATH", path)
    monkeypatch.setattr(auth, "_migrate_legacy_token", lambda: None)
    return path


def test_credentials_loaded_without_scopes_override(token, monkeypatch):
    calls = []

    def fake_load(path, *args, **kwargs):
        calls.append((args, kwargs))

        class Ok:
            valid = True

        return Ok()

    monkeypatch.setattr(auth.Credentials, "from_authorized_user_file", fake_load)
    auth.get_credentials()
    assert calls == [((), {})]


def test_refresh_error_becomes_auth_error(token, monkeypatch):
    monkeypatch.setattr(auth.Credentials, "from_authorized_user_file", lambda *a, **k: _Creds())
    with pytest.raises(auth.AuthError, match="cha-data auth login"):
        auth.get_credentials()


def test_scope_gap_lists_missing_configured_scopes():
    granted = [s for s in auth.scopes() if not s.endswith((".profile.readonly", ".settings.readonly"))]
    gap = auth.scope_gap(granted)
    assert sorted(g.rsplit(".", 2)[1] for g in gap) == ["profile", "settings"]
    assert auth.scope_gap(auth.scopes()) == []


def test_status_reports_gap(monkeypatch, capsys):
    monkeypatch.setattr(auth, "get_credentials", lambda: type("C", (), {
        "valid": True, "expiry": None, "scopes": auth.scopes()[:3]})())
    auth._cli_status()
    out = capsys.readouterr().out
    assert "missing (re-consent needed)" in out and "profile.readonly" in out


@pytest.mark.parametrize(("data_type", "cap"), [("steps", 90), ("active-minutes", 14)])
def test_rollup_windows_respect_caps(monkeypatch, data_type, cap):
    svc = FakeService({"dailyRollUp": [{}]})
    monkeypatch.setattr(client, "service", lambda: svc)
    list(client.iter_daily_rollups(data_type, date(2026, 1, 1), date(2026, 8, 1)))
    spans = []
    for _, kw in svc.points.calls:
        r = kw["body"]["range"]
        a, b = r["start"]["date"], r["end"]["date"]
        spans.append((date(b["year"], b["month"], b["day"]) - date(a["year"], a["month"], a["day"])).days)
    assert spans and max(spans) <= cap
    assert len(spans) > 1
