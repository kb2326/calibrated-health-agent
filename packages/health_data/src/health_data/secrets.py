"""Secret Manager access: read the latest version, write a new one and prune the old.

Secret Manager's free tier allows 6 active versions per month, so `write_secret`
keeps exactly one: after adding a version it disables then destroys every other
one. Values are never logged.
"""
from __future__ import annotations

from typing import Any


def _client(client: Any | None) -> Any:
    if client is not None:
        return client
    from google.cloud import secretmanager

    return secretmanager.SecretManagerServiceClient()


def read_secret(project: str, name: str, *, client: Any | None = None) -> str:
    """Return the payload of the latest version of `name` as text."""
    path = f"projects/{project}/secrets/{name}/versions/latest"
    return _client(client).access_secret_version(request={"name": path}).payload.data.decode("utf-8")


def write_secret(project: str, name: str, value: str, *, client: Any | None = None) -> None:
    """Add `value` as a new version, then disable and destroy every older version."""
    sm = _client(client)
    parent = f"projects/{project}/secrets/{name}"
    newest = sm.add_secret_version(request={"parent": parent, "payload": {"data": value.encode("utf-8")}})
    for version in sm.list_secret_versions(request={"parent": parent}):
        if version.name == newest.name or _state(version) == "DESTROYED":
            continue
        if _state(version) == "ENABLED":
            sm.disable_secret_version(request={"name": version.name})
        sm.destroy_secret_version(request={"name": version.name})


def _state(version: Any) -> str:
    state = version.state
    return getattr(state, "name", str(state))
