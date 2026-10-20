"""OAuth2 for the Google Health API, on Google's own client libraries.

This used to be a hand-rolled flow: a consent URL, a loopback HTTP server, a
code catcher, a token exchange, a refresh call. `google-auth-oauthlib` does
all of that — and adds PKCE and state validation the hand-rolled version
never had — so the whole thing is now `InstalledAppFlow.run_local_server()`.

Credentials live in two files, matching the convention the Google libraries
and the gcloud ecosystem expect:

    config/client_secret.json   the OAuth client downloaded from the console
    config/token.json           the resulting user tokens (refreshed in place)

Both are gitignored. Nothing here ever sees your Google password — only the
authorization code the browser hands back on the loopback redirect.

Run:
    uv run python -m health_data.auth import-client <client_secret.json>   # adopt a client
    uv run cha-data auth login                                             # authorize
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


FORMS_SCOPE = "https://www.googleapis.com/auth/forms.responses.readonly"
REAUTH_MESSAGE = "Run `cha-data auth login` then `cha-data auth push-secret`"


class AuthError(RuntimeError):
    pass


class ReauthRequired(AuthError):  # noqa: N818 - public name fixed by the interface contract
    """The stored refresh token is no longer accepted (invalid_grant); a human must re-consent."""


def scopes() -> list[str]:
    cfg = yaml.safe_load(HEALTH_YAML.read_text())
    prefix = cfg["oauth_scope_prefix"]
    return [f"{prefix}.{cat}.readonly" for cat in cfg["scope_categories"]]


def login_scopes() -> list[str]:
    """Health read-only scopes plus the Forms responses scope: one consent, one owner token."""
    return [*scopes(), FORMS_SCOPE]


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


def _cloud_token() -> dict:
    """The owner token from Secret Manager, completed with the client when it lacks one."""
    from health_data import secrets

    settings = get_settings()
    info = json.loads(secrets.read_secret(settings.gcp_project, settings.token_secret or ""))
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
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            raise ReauthRequired(REAUTH_MESSAGE) from None
        if not cloud:
            TOKEN_PATH.write_text(creds.to_json())
        return creds
    raise ReauthRequired(f"stored credentials are unusable. {REAUTH_MESSAGE}")


def get_forms_credentials() -> Credentials:
    """Credentials for the Forms responses API.

    Cloud: the single owner token. Local: config/token.json when it was granted the
    Forms scope, else the legacy config/forms_token.json.
    """
    settings = get_settings()
    if settings.token_secret:
        return get_credentials()
    if TOKEN_PATH.exists() and FORMS_SCOPE in (json.loads(TOKEN_PATH.read_text()).get("scopes") or []):
        return get_credentials()
    path = settings.forms_token_path
    if not path.exists():
        raise AuthError(f"no Forms token ({TOKEN_PATH} lacks the Forms scope, {path} missing): {REAUTH_MESSAGE}")
    creds = Credentials.from_authorized_user_file(str(path), [FORMS_SCOPE])
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError:
            raise ReauthRequired(REAUTH_MESSAGE) from None
        path.write_text(creds.to_json())
    return creds


def push_secrets() -> None:
    """Upload config/client_secret.json and config/token.json to Secret Manager."""
    from health_data import secrets

    settings = get_settings()
    if not settings.token_secret or not settings.client_secret_secret:
        raise AuthError("CHA_TOKEN_SECRET and CHA_CLIENT_SECRET_SECRET must both be set")
    for path, name in ((CLIENT_SECRET_PATH, settings.client_secret_secret), (TOKEN_PATH, settings.token_secret)):
        if not path.exists():
            raise AuthError(f"{path} not found - run: cha-data auth login")
        secrets.write_secret(settings.gcp_project, name, path.read_text())
        print(f"pushed {path.name} to secret {name}")


def _cli_login() -> None:
    if not CLIENT_SECRET_PATH.exists():
        raise AuthError(
            f"{CLIENT_SECRET_PATH} not found. Download an OAuth client of type "
            '"Desktop app" from the Cloud console, then run:\n'
            "  uv run python -m health_data.auth import-client <downloaded.json>"
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), login_scopes())
    # port=0 lets the OS pick a free port; the library registers the matching
    # loopback redirect, runs the server, and validates state + PKCE for us.
    creds = flow.run_local_server(port=0, prompt="consent")
    TOKEN_PATH.write_text(creds.to_json())
    print("Authorized. Tokens saved to", TOKEN_PATH)


def scope_gap(granted: list[str] | None) -> list[str]:
    """Configured scopes the token has not been granted."""
    have = set(granted or [])
    return [s for s in scopes() if s not in have]


def _cli_status() -> None:
    creds = get_credentials()
    print("valid        :", creds.valid)
    print("expiry       :", creds.expiry)
    print("granted scopes:")
    for s in creds.scopes or []:
        print("  ", s)
    print("configured scopes:", len(scopes()))
    missing = scope_gap(list(creds.scopes or []))
    print("missing (re-consent needed):" if missing else "missing: none")
    for s in missing:
        print("  ", s)
    if FORMS_SCOPE not in (creds.scopes or []):
        print("forms scope missing (journal import needs re-consent): cha-data auth login")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "login"
    try:
        if cmd == "login":
            _cli_login()
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
            print(f"Unknown command: {cmd}. Use 'login', 'import-client', or 'status'.")
    except AuthError as e:
        print(f"Auth error: {e}", file=sys.stderr)
        sys.exit(1)
