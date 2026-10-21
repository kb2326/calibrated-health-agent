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


def test_write_secret_keeps_previous_disabled_and_destroys_older():
    p = "projects/p/secrets/tok"
    fake = FakeSecretManager(versions=[
        _version(f"{p}/versions/7", "DISABLED"),
        _version(f"{p}/versions/8", "ENABLED"),
        _version(f"{p}/versions/5", "ENABLED"),
        _version(f"{p}/versions/6", "DESTROYED"),
    ])
    secrets.write_secret("p", "tok", "v", client=fake)
    assert fake.calls == [
        ("add", p),
        ("disable", f"{p}/versions/8"),  # N-1: disabled, kept for rollback
        ("destroy", f"{p}/versions/7"),
        ("disable", f"{p}/versions/5"), ("destroy", f"{p}/versions/5"),
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


def _settings(**kw):
    base = {"token_secret": "tok", "client_secret_secret": "cli", "gcp_project": "p"}
    return Settings.model_validate({**base, **kw})


def _push_setup(monkeypatch, tmp_path, *, forms=True, forms_secret="ftok"):
    (tmp_path / "client.json").write_text("CLIENT")
    (tmp_path / "token.json").write_text("TOKEN")
    if forms:
        (tmp_path / "forms_token.json").write_text("FTOKEN")
    monkeypatch.setattr(auth, "CLIENT_SECRET_PATH", tmp_path / "client.json")
    monkeypatch.setattr(auth, "TOKEN_PATH", tmp_path / "token.json")
    settings = _settings(forms_token_secret=forms_secret, forms_token_path=str(tmp_path / "forms_token.json"))
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    written: list[tuple] = []
    monkeypatch.setattr(
        secrets, "write_secret", lambda project, name, value, **k: written.append((project, name, value)))
    return written


def test_push_secrets_uploads_three_files(monkeypatch, tmp_path):
    written = _push_setup(monkeypatch, tmp_path)
    auth.push_secrets()
    assert written == [("p", "cli", "CLIENT"), ("p", "tok", "TOKEN"), ("p", "ftok", "FTOKEN")]


def test_push_secrets_skips_missing_forms_token(monkeypatch, tmp_path, capsys):
    written = _push_setup(monkeypatch, tmp_path, forms=False)
    auth.push_secrets()
    assert written == [("p", "cli", "CLIENT"), ("p", "tok", "TOKEN")]
    assert "login-forms" in capsys.readouterr().out


class _FakeFlow:
    instances: list = []

    def __init__(self, scopes):
        self.scopes = scopes

    @classmethod
    def from_client_secrets_file(cls, path, scopes):
        inst = cls(scopes)
        cls.instances.append(inst)
        return inst

    def run_local_server(self, **kw):
        return SimpleNamespace(to_json=lambda: '{"fake": true}')


def _login_setup(monkeypatch, tmp_path):
    _FakeFlow.instances = []
    (tmp_path / "client.json").write_text("{}")
    monkeypatch.setattr(auth, "CLIENT_SECRET_PATH", tmp_path / "client.json")
    monkeypatch.setattr(auth, "TOKEN_PATH", tmp_path / "token.json")
    monkeypatch.setattr(auth, "get_settings", lambda: _settings(forms_token_path=str(tmp_path / "forms_token.json")))
    monkeypatch.setattr(auth, "InstalledAppFlow", _FakeFlow)


def test_health_login_requests_only_health_scopes(monkeypatch, tmp_path):
    _login_setup(monkeypatch, tmp_path)
    auth._cli_login()
    assert _FakeFlow.instances[0].scopes == auth.scopes()
    assert (tmp_path / "token.json").exists() and not (tmp_path / "forms_token.json").exists()


def test_forms_login_requests_exactly_the_two_forms_scopes(monkeypatch, tmp_path):
    _login_setup(monkeypatch, tmp_path)
    auth._cli_login_forms()
    assert _FakeFlow.instances[0].scopes == [
        "https://www.googleapis.com/auth/forms.responses.readonly",
        "https://www.googleapis.com/auth/forms.body.readonly",
    ]
    assert (tmp_path / "forms_token.json").exists() and not (tmp_path / "token.json").exists()


def test_health_and_forms_scopes_are_disjoint():
    assert not set(auth.scopes()) & set(auth.FORMS_SCOPES)
    assert not hasattr(auth, "login_scopes")


def test_forms_credentials_cloud_reads_forms_secret(monkeypatch):
    fake = FakeSecretManager(values={
        "ftok": json.dumps({"refresh_token": "fr", "client_id": "id", "client_secret": "s"}),  # noqa: S106
    })
    monkeypatch.setattr(auth, "get_settings", lambda: _settings(forms_token_secret="ftok"))
    monkeypatch.setattr(secrets, "_client", lambda client: fake)
    seen = {}

    class C:
        valid = True

    monkeypatch.setattr(auth.Credentials, "from_authorized_user_info", lambda info, *a, **k: seen.update(info) or C())
    assert auth.get_forms_credentials().valid
    assert seen["refresh_token"] == "fr"
    assert [c[1] for c in fake.calls] == ["projects/p/secrets/ftok/versions/latest"]


def test_forms_invalid_grant_names_login_forms(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", lambda: _settings(forms_token_secret="ftok"))
    monkeypatch.setattr(auth, "_cloud_token", lambda name=None: {"refresh_token": "r"})
    monkeypatch.setattr(auth.Credentials, "from_authorized_user_info", lambda *a, **k: _Creds())
    with pytest.raises(auth.ReauthRequired, match="cha-data auth login-forms"):
        auth.get_forms_credentials()


def test_forms_credentials_local_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "get_settings", lambda: Settings.model_validate(
        {"forms_token_path": str(tmp_path / "nope.json")}))
    with pytest.raises(auth.AuthError, match="login-forms"):
        auth.get_forms_credentials()


def test_auth_status_reports_both_tokens(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(auth, "TOKEN_PATH", tmp_path / "token.json")
    monkeypatch.setattr(auth, "get_settings", lambda: _settings(
        token_secret=None, forms_token_path=str(tmp_path / "forms_token.json")))
    hs = auth.scopes()
    (tmp_path / "token.json").write_text(json.dumps({"scopes": hs[:-1], "client_secret": "SUPERSECRET"}))
    (tmp_path / "forms_token.json").write_text(json.dumps(
        {"scopes": [auth.FORMS_SCOPES[0]], "refresh_token": "SUPERSECRET"}))
    auth._cli_status()
    out = capsys.readouterr().out
    assert "SUPERSECRET" not in out
    assert "Health token" in out and "Forms token" in out
    assert hs[-1] in out  # missing Health scope
    assert auth.FORMS_SCOPES[1] in out  # missing Forms scope


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
