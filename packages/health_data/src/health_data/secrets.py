"""Secret Manager access: read the latest version, write a new one and prune the old.

Secret Manager's free tier allows 6 active versions per month (3 secrets here), so
`write_secret` keeps two per secret: the new version (enabled) and the one before it,
disabled but restorable for a rollback. Every older version is disabled and destroyed.
Values are never logged.
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
    """Add `value` as a new version; keep the previous one disabled; destroy the rest."""
    sm = _client(client)
    parent = f"projects/{project}/secrets/{name}"
    newest = sm.add_secret_version(request={"parent": parent, "payload": {"data": value.encode("utf-8")}})
    older = sorted(
        (v for v in sm.list_secret_versions(request={"parent": parent})
         if v.name != newest.name and _state(v) != "DESTROYED"),
        key=_number, reverse=True,
    )
    for i, version in enumerate(older):
        if _state(version) == "ENABLED":
            sm.disable_secret_version(request={"name": version.name})
        if i > 0:  # keep N-1 (the most recent previous version) for rollback
            sm.destroy_secret_version(request={"name": version.name})


def _number(version: Any) -> int:
    tail = str(version.name).rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else -1


def _state(version: Any) -> str:
    state = version.state
    return getattr(state, "name", str(state))
