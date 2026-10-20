"""GCS-backed database persistence with optimistic concurrency (object generations).

GCS is the source of truth. A local pull records the object generation in
`data/.db_generation`; every upload is conditional on that generation, so two writers
can never silently overwrite each other.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from google.api_core.exceptions import PreconditionFailed
from health_core.settings import get_settings


class ConcurrentUpdateError(RuntimeError):
    """The bucket object changed since the local copy was pulled; nothing was uploaded."""


class StaleLocalDbError(RuntimeError):
    """The local database is not the bucket's current generation; pull before writing."""


def _client(client: Any | None) -> Any:
    if client is not None:
        return client
    from google.cloud import storage

    return storage.Client(project=get_settings().gcp_project)


def _gen_path(gen_path: Path | None) -> Path:
    return gen_path or get_settings().data_dir / ".db_generation"


def recorded_generation(gen_path: Path | None = None) -> int | None:
    path = _gen_path(gen_path)
    if not path.exists():
        return None
    text = path.read_text().strip()
    return int(text) if text else None


def _record(generation: int | None, gen_path: Path | None) -> None:
    path = _gen_path(gen_path)
    if generation is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(generation))


def _remote_generation(bucket: str, obj: str, client: Any) -> int | None:
    blob = client.bucket(bucket).get_blob(obj)
    return None if blob is None else int(blob.generation)


def pull_db(bucket: str, obj: str, dest: Path, *, client: Any | None = None, gen_path: Path | None = None) -> int | None:
    """Download the object to `dest`; return its generation (None if absent) and record it."""
    blob = _client(client).bucket(bucket).get_blob(obj)
    if blob is None:
        _record(None, gen_path)
        return None
    generation = int(blob.generation)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    blob.download_to_filename(str(tmp), if_generation_match=generation)
    for suffix in ("-wal", "-shm"):  # stale sidecars would corrupt the pulled file
        Path(str(dest) + suffix).unlink(missing_ok=True)
    os.replace(tmp, dest)
    _record(generation, gen_path)
    return generation


def push_db(
    bucket: str,
    obj: str,
    src: Path,
    if_generation_match: int | None,
    *,
    client: Any | None = None,
    gen_path: Path | None = None,
) -> int:
    """Upload `src` iff the object is still at `if_generation_match` (0 = must not exist)."""
    conn = sqlite3.connect(src)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # fold -wal into the main file
    finally:
        conn.close()
    blob = _client(client).bucket(bucket).blob(obj)
    try:
        blob.upload_from_filename(str(src), if_generation_match=if_generation_match)
    except PreconditionFailed as exc:
        raise ConcurrentUpdateError(
            f"{obj} changed in the bucket since it was pulled; pull again and redo the write"
        ) from exc
    generation = int(blob.generation)
    _record(generation, gen_path)
    return generation


def require_fresh(bucket: str, obj: str, *, client: Any | None = None, gen_path: Path | None = None) -> None:
    """Raise StaleLocalDbError unless the local copy matches the bucket's current generation."""
    remote = _remote_generation(bucket, obj, _client(client))
    local = recorded_generation(gen_path)
    if remote != local:
        raise StaleLocalDbError(f"local database is stale (local generation {local}, bucket {remote}); run `cha-data db pull`")


def push_recorded(bucket: str, obj: str, src: Path, *, client: Any | None = None, gen_path: Path | None = None) -> int:
    """Push using the recorded generation; no recorded generation means create (precondition 0)."""
    local = recorded_generation(gen_path)
    return push_db(bucket, obj, src, 0 if local is None else local, client=client, gen_path=gen_path)
