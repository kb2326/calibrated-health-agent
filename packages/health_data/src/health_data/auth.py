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
    uv run python -m health_data.auth login                                # authorize
    uv run python -m health_data.auth status                               # verify
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import yaml
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


class AuthError(RuntimeError):
    pass


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


def get_credentials() -> Credentials:
    """Valid user credentials, refreshing silently when the token has aged out.

    Never launches a browser: unattended callers (sync, analyze, the scheduler)
    must fail loudly rather than block waiting for a human.
    """
    _migrate_legacy_token()
    if not TOKEN_PATH.exists():
        raise AuthError(
            f"{TOKEN_PATH} not found — run: uv run python -m health_data.auth login"
        )
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), scopes())
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
        return creds
    raise AuthError(
        "stored credentials are unusable and cannot be refreshed — "
        "re-run: uv run python -m health_data.auth login"
    )


def _cli_login() -> None:
    if not CLIENT_SECRET_PATH.exists():
        raise AuthError(
            f"{CLIENT_SECRET_PATH} not found. Download an OAuth client of type "
            '"Desktop app" from the Cloud console, then run:\n'
            "  uv run python -m health_data.auth import-client <downloaded.json>"
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), scopes())
    # port=0 lets the OS pick a free port; the library registers the matching
    # loopback redirect, runs the server, and validates state + PKCE for us.
    creds = flow.run_local_server(port=0, prompt="consent")
    TOKEN_PATH.write_text(creds.to_json())
    print("Authorized. Tokens saved to", TOKEN_PATH)


def _cli_status() -> None:
    creds = get_credentials()
    print("valid        :", creds.valid)
    print("expiry       :", creds.expiry)
    print("scopes       :")
    for s in creds.scopes or []:
        print("  ", s)


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
        elif cmd == "status":
            _cli_status()
        else:
            print(f"Unknown command: {cmd}. Use 'login', 'import-client', or 'status'.")
    except AuthError as e:
        print(f"Auth error: {e}", file=sys.stderr)
        sys.exit(1)
