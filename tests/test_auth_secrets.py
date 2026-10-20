"""Credentials from Secret Manager, reauth signalling, push-secret and version pruning (no network)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from google.auth.exceptions import RefreshError
from health_core.settings import Settings
from health_data import auth, secrets


def _version(name: str, state: str):
    return SimpleNamespace(name=name, state=state)


class FakeSecretManager:
    def __init__(self, values=None, versions=None):
        self.values = values or {}
        self.versions = versions or []
        self.calls: list[tuple[str, str]] = []

    def access_secret_version(self, request):
        self.calls.append(("access", request["name"]))
        name = request["name"].split("/secrets/")[1].split("/")[0]
        return SimpleNamespace(payload=SimpleNamespace(data=self.values[name].encode()))

    def add_secret_version(self, request):
        self.calls.append(("add", request["parent"]))
        return _version(f"{request['parent']}/versions/9", "ENABLED")

    def list_secret_versions(self, request):
        return [*self.versions, _version(f"{request['parent']}/versions/9", "ENABLED")]

    def disable_secret_version(self, request):
        self.calls.append(("disable", request["name"]))

    def destroy_secret_version(self, request):
        self.calls.append(("destroy", request["name"]))


def test_write_secret_destroys_all_but_newest():
    p = "projects/p/secrets/tok"
    fake = FakeSecretManager(versions=[
        _version(f"{p}/versions/7", "ENABLED"),
        _version(f"{p}/versions/8", "DISABLED"),
        _version(f"{p}/versions/6", "DESTROYED"),
    ])
    secrets.write_secret("p", "tok", "v", client=fake)
    assert fake.calls == [
        ("add", p),
        ("disable", f"{p}/versions/7"), ("destroy", f"{p}/versions/7"),
        ("destroy", f"{p}/versions/8"),
    ]


def test_read_secret_returns_latest_text():
    fake = FakeSecretManager(values={"tok": "hello"})
    assert secrets.read_secret("p", "tok", client=fake) == "hello"
    assert fake.calls == [("access", "projects/p/secrets/tok/versions/latest")]


class _Creds:
    valid = False
    expired = True
    refresh_token = "r"  # noqa: S105

    def refresh(self, _request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")


def test_invalid_grant_raises_reauth_required(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", lambda: Settings.model_validate(
        {"token_secret": "tok", "client_secret_secret": "cli"}))
    monkeypatch.setattr(auth, "_cloud_token", lambda: {"refresh_token": "r"})
    monkeypatch.setattr(auth.Credentials, "from_authorized_user_info", lambda *a, **k: _Creds())
    with pytest.raises(auth.ReauthRequired, match="cha-data auth login.*cha-data auth push-secret"):
        auth.get_credentials()


def test_cloud_token_fills_client_from_client_secret(monkeypatch):
    fake = FakeSecretManager(values={
        "tok": json.dumps({"refresh_token": "r"}),
        "cli": json.dumps({"installed": {"client_id": "id", "client_secret": "sec"}}),
    })
    monkeypatch.setattr(auth, "get_settings", lambda: Settings.model_validate(
        {"token_secret": "tok", "client_secret_secret": "cli", "gcp_project": "p"}))
    monkeypatch.setattr(secrets, "_client", lambda client: fake)
    info = auth._cloud_token()
    assert info["client_id"] == "id" and info["client_secret"] == "sec"


def test_push_secrets_uploads_both_files(monkeypatch, tmp_path):
    (tmp_path / "client.json").write_text("CLIENT")
    (tmp_path / "token.json").write_text("TOKEN")
    monkeypatch.setattr(auth, "CLIENT_SECRET_PATH", tmp_path / "client.json")
    monkeypatch.setattr(auth, "TOKEN_PATH", tmp_path / "token.json")
    monkeypatch.setattr(auth, "get_settings", lambda: Settings.model_validate(
        {"token_secret": "tok", "client_secret_secret": "cli", "gcp_project": "p"}))
    written: list[tuple] = []
    monkeypatch.setattr(
        secrets, "write_secret", lambda project, name, value, **k: written.append((project, name, value)))
    auth.push_secrets()
    assert written == [("p", "cli", "CLIENT"), ("p", "tok", "TOKEN")]


def test_login_requests_health_plus_forms_scope():
    assert auth.login_scopes()[:-1] == auth.scopes()
    assert auth.login_scopes()[-1] == "https://www.googleapis.com/auth/forms.responses.readonly"
    assert all(s.endswith(".readonly") for s in auth.login_scopes())


def test_refresh_token_without_expiry_is_refreshed(monkeypatch):
    """Real Credentials: a secret holding only a refresh token (no token/expiry) must refresh."""
    from google.oauth2 import credentials as oauth_creds
    from google.oauth2 import reauth

    monkeypatch.setattr(auth, "get_settings", lambda: Settings.model_validate({"token_secret": "tok"}))
    monkeypatch.setattr(auth, "_cloud_token", lambda: {
        "refresh_token": "r", "client_id": "id", "client_secret": "s",  # noqa: S106
        "token_uri": "https://oauth2.googleapis.com/token"})
    # Real Credentials with no token and no expiry: `expired` is False here, `valid` is False.
    bare = oauth_creds.Credentials(
        None, refresh_token="r", client_id="id", client_secret="s",  # noqa: S106
        token_uri="https://oauth2.googleapis.com/token")
    assert not bare.expired and not bare.valid
    monkeypatch.setattr(oauth_creds.Credentials, "from_authorized_user_info", lambda *a, **k: bare)
    refreshed = []

    def fake_refresh(*a, **k):
        refreshed.append(1)
        from datetime import datetime, timedelta
        return "access", "r", datetime.utcnow() + timedelta(hours=1), {}, None

    monkeypatch.setattr(reauth, "refresh_grant", fake_refresh)
    creds = auth.get_credentials()
    assert refreshed and creds.valid
