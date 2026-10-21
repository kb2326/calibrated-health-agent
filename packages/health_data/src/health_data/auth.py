"""OAuth2 for the Google Health API, on Google's own client libraries.

This used to be a hand-rolled flow: a consent URL, a loopback HTTP server, a
code catcher, a token exchange, a refresh call. `google-auth-oauthlib` does
all of that — and adds PKCE and state validation the hand-rolled version
never had — so the whole thing is now `InstalledAppFlow.run_local_server()`.

Credentials live in two files, matching the convention the Google libraries
and the gcloud ecosystem expect:

    config/client_secret.json   the OAuth client downloaded from the console
    config/token.json           Health user token (refreshed in place)
    config/forms_token.json     separate Forms token (journal import)

Both are gitignored. Nothing here ever sees your Google password — only the
authorization code the browser hands back on the loopback redirect.

Run:
    uv run python -m health_data.auth import-client <client_secret.json>   # adopt a client
    uv run cha-data auth login                                             # Health consent
    uv run cha-data auth login-forms                                       # Forms consent
    uv run cha-data auth status                                            # verify
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import yaml
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from health_core.settings import get_settings

CONFIG_DIR = get_settings().config_dir
CLIENT_SECRET_PATH = CONFIG_DIR / "client_secret.json"
TOKEN_PATH = CONFIG_DIR / "token.json"
HEALTH_YAML = CONFIG_DIR / "health.yaml"

# Legacy single-file layout from the hand-rolled implementation, still read
# once so an existing authorization survives the migration.
LEGACY_CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"


# Two separate tokens. The Health API rejects (403 "disallowed OAuth scope") any
# access token that also carries a non-Health scope, so Forms gets its own.
FORMS_SCOPES = [
    "https://www.googleapis.com/auth/forms.responses.readonly",
    "https://www.googleapis.com/auth/forms.body.readonly",  # forms.get: question title -> id
]
REAUTH_MESSAGE = "Run `cha-data auth login` then `cha-data auth push-secret`"
FORMS_REAUTH_MESSAGE = "Run `cha-data auth login-forms` then `cha-data auth push-secret`"


class AuthError(RuntimeError):
    pass


class ReauthRequired(AuthError):  # noqa: N818 - public name fixed by the interface contract
    """The stored refresh token is no longer accepted (invalid_grant); a human must re-consent."""


def scopes() -> list[str]:
    cfg = yaml.safe_load(HEALTH_YAML.read_text())
    prefix = cfg["oauth_scope_prefix"]
    return [f"{prefix}.{cat}.readonly" for cat in cfg["scope_categories"]]


def _migrate_legacy_token() -> None:
    """Carry a pre-migration credentials.json over to the new layout."""
    if TOKEN_PATH.exists() or not LEGACY_CREDENTIALS_PATH.exists():
        return
    old = json.loads(LEGACY_CREDENTIALS_PATH.read_text())
    if not old.get("refresh_token"):
        return
    TOKEN_PATH.write_text(
        json.dumps(
            {
                "token": old.get("access_token"),
                "refresh_token": old["refresh_token"],
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": old["client_id"],
                "client_secret": old["client_secret"],
                "scopes": scopes(),
            },
            indent=2,
        )
    )
    if not CLIENT_SECRET_PATH.exists():
        CLIENT_SECRET_PATH.write_text(
            json.dumps(
                {"installed": {"client_id": old["client_id"], "client_secret": old["client_secret"]}},
                indent=2,
            )
        )


def import_client(path: str) -> str:
    """Adopt an OAuth client JSON downloaded from the Cloud console."""
    raw = json.loads(Path(path).read_text())
    kind = next((k for k in ("installed", "web") if k in raw), None)
    if kind is None:
        raise AuthError(
            f"{path} doesn't look like a Google OAuth client file "
            '(expected a top-level "installed" or "web" key).'
        )
    CONFIG_DIR.mkdir(exist_ok=True)
    shutil.copyfile(path, CLIENT_SECRET_PATH)
    # A different client invalidates any stored token.
    if TOKEN_PATH.exists():
        stored = json.loads(TOKEN_PATH.read_text())
        if stored.get("client_id") != raw[kind]["client_id"]:
            TOKEN_PATH.unlink()
    return kind


def _cloud_token(secret_name: str | None = None) -> dict:
    """A token from Secret Manager (default: the Health one), completed with the client when it lacks one."""
    from health_data import secrets

    settings = get_settings()
    info = json.loads(secrets.read_secret(settings.gcp_project, secret_name or settings.token_secret or ""))
    if settings.client_secret_secret and not (info.get("client_id") and info.get("client_secret")):
        raw = json.loads(secrets.read_secret(settings.gcp_project, settings.client_secret_secret))
        client = raw[next(k for k in ("installed", "web") if k in raw)]
        info.setdefault("client_id", client["client_id"])
        info.setdefault("client_secret", client["client_secret"])
        info.setdefault("token_uri", "https://oauth2.googleapis.com/token")
    return info


def get_credentials() -> Credentials:
    """Valid user credentials, refreshing silently when the token has aged out.

    With `CHA_TOKEN_SECRET` set (the cloud job) the client and token come from
    Secret Manager and a refreshed access token stays in memory; otherwise they
    are read from config/. Never launches a browser: unattended callers must
    fail loudly rather than block waiting for a human.
    """
    cloud = bool(get_settings().token_secret)
    if cloud:
        # No scopes override: a refresh must request exactly what the token was granted.
        creds = Credentials.from_authorized_user_info(_cloud_token())  # type: ignore[no-untyped-call]
    else:
        _migrate_legacy_token()
        if not TOKEN_PATH.exists():
            raise AuthError(f"{TOKEN_PATH} not found - run: cha-data auth login")
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    if creds.valid:
        return creds
    if not creds.valid and creds.refresh_token:  # `expired` is False when expiry is unset
        try:
            creds.refresh(Request())
        except RefreshError:
            raise ReauthRequired(REAUTH_MESSAGE) from None
        if not cloud:
            TOKEN_PATH.write_text(creds.to_json())
        return creds
    raise ReauthRequired(f"stored credentials are unusable. {REAUTH_MESSAGE}")


def get_forms_credentials() -> Credentials:
    """Credentials for the Forms API, from the separate Forms token.

    Cloud (`CHA_FORMS_TOKEN_SECRET` set): Secret Manager. Local: config/forms_token.json.
    """
    settings = get_settings()
    cloud = bool(settings.forms_token_secret)
    path = settings.forms_token_path
    if cloud:
        creds = Credentials.from_authorized_user_info(_cloud_token(settings.forms_token_secret))  # type: ignore[no-untyped-call]
    else:
        if not path.exists():
            raise AuthError(f"{path} not found - run: cha-data auth login-forms")
        creds = Credentials.from_authorized_user_file(str(path))
    if creds.valid:
        return creds
    if creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            raise ReauthRequired(FORMS_REAUTH_MESSAGE) from None
        if not cloud:
            path.write_text(creds.to_json())
        return creds
    raise ReauthRequired(f"stored Forms credentials are unusable. {FORMS_REAUTH_MESSAGE}")


def push_secrets() -> None:
    """Upload the OAuth client, Health token and Forms token to Secret Manager."""
    from health_data import secrets

    settings = get_settings()
    if not settings.token_secret or not settings.client_secret_secret:
        raise AuthError("CHA_TOKEN_SECRET and CHA_CLIENT_SECRET_SECRET must both be set")
    targets = [
        (CLIENT_SECRET_PATH, settings.client_secret_secret, True, "cha-data auth login"),
        (TOKEN_PATH, settings.token_secret, True, "cha-data auth login"),
        (settings.forms_token_path, settings.forms_token_secret, False, "cha-data auth login-forms"),
    ]
    for path, name, required, hint in targets:
        if not name:
            print(f"skipped {path.name}: no secret name configured (CHA_FORMS_TOKEN_SECRET)")
            continue
        if not path.exists():
            if required:
                raise AuthError(f"{path} not found - run: {hint}")
            print(f"skipped {path.name}: not found - run: {hint}")
            continue
        secrets.write_secret(settings.gcp_project, name, path.read_text())
        print(f"pushed {path.name} to secret {name}")


def _login(scope_list: list[str], token_path: Path) -> None:
    if not CLIENT_SECRET_PATH.exists():
        raise AuthError(
            f"{CLIENT_SECRET_PATH} not found. Download an OAuth client of type "
            '"Desktop app" from the Cloud console, then run:\n'
            "  uv run python -m health_data.auth import-client <downloaded.json>"
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), scope_list)
    # port=0 lets the OS pick a free port; the library registers the matching
    # loopback redirect, runs the server, and validates state + PKCE for us.
    creds = flow.run_local_server(port=0, prompt="consent")
    token_path.write_text(creds.to_json())
    print("Authorized. Tokens saved to", token_path)


def _cli_login() -> None:
    """Health read-only scopes only."""
    _login(scopes(), TOKEN_PATH)


def _cli_login_forms() -> None:
    """Forms scopes only (a separate token: mixing them breaks the Health API)."""
    _login(FORMS_SCOPES, get_settings().forms_token_path)


def scope_gap(granted: list[str] | None, expected: list[str] | None = None) -> list[str]:
    """Expected scopes (default: the configured Health ones) the token has not been granted."""
    have = set(granted or [])
    return [s for s in (scopes() if expected is None else expected) if s not in have]


def _report_token(label: str, path: Path, expected: list[str], login_cmd: str) -> None:
    """Granted vs expected scopes from the token file; never prints secret fields."""
    print(f"{label} ({path.name}):")
    if not path.exists():
        print(f"  not found - run: {login_cmd}")
        return
    granted = json.loads(path.read_text()).get("scopes") or []
    print(f"  granted scopes: {len(granted)}")
    for s in granted:
        print("    ", s)
    missing = scope_gap(granted, expected)
    print(f"  expected {len(expected)}; missing: {'none' if not missing else ''}")
    for s in missing:
        print("    ", s)
    extra = [s for s in granted if s not in expected]
    if extra:
        print(f"  unexpected extra scopes (re-run: {login_cmd}):")
        for s in extra:
            print("    ", s)


def _cli_status() -> None:
    _migrate_legacy_token()
    _report_token("Health token", TOKEN_PATH, scopes(), "cha-data auth login")
    _report_token("Forms token", get_settings().forms_token_path, FORMS_SCOPES, "cha-data auth login-forms")
    if not TOKEN_PATH.exists():  # the Health token is required; the Forms one only for journal import
        raise AuthError(f"{TOKEN_PATH} not found - run: cha-data auth login")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "login"
    try:
        if cmd == "login":
            _cli_login()
        elif cmd == "login-forms":
            _cli_login_forms()
        elif cmd == "import-client":
            if len(sys.argv) < 3:
                raise AuthError("usage: uv run python -m health_data.auth import-client <client_secret.json>")
            kind = import_client(sys.argv[2])
            print(f"Imported {'Desktop app' if kind == 'installed' else 'Web app'} client.")
            if kind == "web":
                print("Note: Desktop-app clients are preferred — they need no redirect URI registration.")
        elif cmd == "push-secret":
            push_secrets()
        elif cmd == "status":
            _cli_status()
        else:
            print(f"Unknown command: {cmd}. Use 'login', 'login-forms', 'import-client', 'push-secret' or 'status'.")
    except AuthError as e:
        print(f"Auth error: {e}", file=sys.stderr)
        sys.exit(1)
