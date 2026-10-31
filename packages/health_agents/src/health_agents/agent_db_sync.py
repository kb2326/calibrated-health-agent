"""One shared agent.db in the bucket, used by the CLI, the laptop web app and the cloud.

A turn pulls the latest copy (if the bucket moved), runs, then pushes with a generation
precondition. If another writer pushed in between (the phone and the laptop at once), this
turn's rows are re-appended onto a fresh copy and pushed once more. A second conflict is
reported as "not_saved", never retried in a loop.

Only inserts happen during a turn (receipts, chat usage, facts, episodes), so "this turn's
rows" are the rows with a rowid above the snapshot taken before the turn.

A watermark ("pushed", the rowids of the last copy that reached the bucket) marks which
local rows are not in the bucket yet. Before a pull replaces the local file, those rows are
read and appended onto the fresh copy, so a turn that was "offline" or "not_saved" is pushed
by the next one instead of being erased.

The generation record and the watermark live in their own folder, apart from health.db's.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from health_core.settings import get_settings
from health_data import store

TURN_TABLES = ("receipts", "chat_usage", "facts", "episodes")
AUTO_ID = {"chat_usage"}  # INTEGER PRIMARY KEY: let the fresh copy assign it

PushResult = Literal["pushed", "reappended", "not_saved"]


def gen_path(db_path: Path | None = None) -> Path:
    base = (db_path.parent if db_path else get_settings().data_dir) / ".agent_db"
    return base / "generation"


def _mark_path(db_path: Path) -> Path:
    return gen_path(db_path).with_name("pushed.json")


def _load_mark(db_path: Path) -> dict[str, int] | None:
    try:
        return {k: int(v) for k, v in json.loads(_mark_path(db_path).read_text()).items()}
    except (OSError, ValueError, AttributeError):
        return None


def _save_mark(db_path: Path, rowids: dict[str, int]) -> None:
    path = _mark_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rowids))


def snapshot_rowids(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    try:
        return {t: int(conn.execute(f"SELECT COALESCE(MAX(rowid), 0) FROM {t}").fetchone()[0])
                for t in TURN_TABLES}
    finally:
        conn.close()


def pull_agent_db(bucket: str, obj: str, dest: Path, *, client: Any | None = None) -> int | None:
    """Download only when the bucket copy moved since our last pull or push.

    Local rows above the watermark (not yet in the bucket) are carried onto the fresh copy,
    and the watermark moves to the fresh copy's rowids, so they stay "to push"."""
    gp = gen_path(dest)
    remote = store.remote_generation(bucket, obj, client=client)
    if remote is None or (remote == store.recorded_generation(gp) and dest.exists()):
        return remote
    mark = _load_mark(dest)
    keep = _turn_rows(dest, mark) if dest.exists() and mark is not None else None
    if dest.exists() and mark is None and any(snapshot_rowids(dest).values()):
        shutil.copyfile(dest, dest.with_name(dest.name + ".before-first-pull"))  # never lose history
    generation = store.pull_db(bucket, obj, dest, client=client, gen_path=gp)
    _save_mark(dest, snapshot_rowids(dest))
    if keep:
        _append(dest, keep)
    return generation


def _turn_rows(path: Path, since: dict[str, int]) -> dict[str, tuple[list[str], list[tuple]]]:
    conn = sqlite3.connect(path)
    try:
        out = {}
        for t in TURN_TABLES:
            cur = conn.execute(f"SELECT * FROM {t} WHERE rowid > ?", (since.get(t, 0),))
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()
            if t in AUTO_ID:
                i = cols.index("id")
                cols = cols[:i] + cols[i + 1:]
                rows = [r[:i] + r[i + 1:] for r in rows]
            out[t] = (cols, rows)
        return out
    finally:
        conn.close()


def _append(path: Path, rows: dict[str, tuple[list[str], list[tuple]]]) -> None:
    conn = sqlite3.connect(path)
    try:
        with conn:
            for t, (cols, values) in rows.items():
                if values:
                    marks = ",".join("?" * len(cols))
                    conn.executemany(f"INSERT OR IGNORE INTO {t} ({','.join(cols)}) VALUES ({marks})",
                                     values)
    finally:
        conn.close()


def _push(bucket: str, obj: str, src: Path, client: Any | None) -> None:
    gp = gen_path(src)
    store.push_db(bucket, obj, src, store.recorded_generation(gp) or 0, client=client, gen_path=gp)


def push_agent_db(bucket: str, obj: str, src: Path, *, since: dict[str, int],
                  client: Any | None = None) -> PushResult:
    try:
        _push(bucket, obj, src, client)
        _save_mark(src, snapshot_rowids(src))
        return "pushed"
    except store.ConcurrentUpdateError:
        pass
    # Another writer pushed first: the re-pull below carries every unpushed row (this turn's
    # and any earlier unsaved ones) onto the fresh copy via the watermark.
    if _load_mark(src) is None:
        _save_mark(src, since)
    try:
        pull_agent_db(bucket, obj, src, client=client)
        _push(bucket, obj, src, client)
        _save_mark(src, snapshot_rowids(src))
        return "reappended"
    except store.ConcurrentUpdateError:
        return "not_saved"  # the rows stay local, above the watermark, for the next turn


@contextmanager
def shared_turn(*, client: Any | None = None) -> Iterator[dict[str, Any]]:
    """Wrap one chat turn: pull before, push after, when a bucket is configured.

    Yields a dict whose "result" is set after the turn: None (no bucket), "pushed",
    "reappended", "not_saved" or "offline" (the bucket could not be reached).
    """
    s = get_settings()
    info: dict[str, Any] = {"result": None}
    if not s.db_bucket:
        yield info
        return
    path = s.agent_db_path
    try:
        pull_agent_db(s.db_bucket, s.agent_db_object, path, client=client)
    except Exception:
        info["result"] = "offline"
    with sqlite_ready(path):
        since = snapshot_rowids(path)
    yield info
    if info["result"] == "offline":
        return
    try:
        info["result"] = push_agent_db(s.db_bucket, s.agent_db_object, path, since=since,
                                       client=client)
    except Exception:
        info["result"] = "offline"


@contextmanager
def sqlite_ready(path: Path) -> Iterator[None]:
    """Make sure the schema exists before reading rowids (a first run has no file)."""
    from . import agent_db

    with agent_db.connect():
        pass
    yield


def seed(bucket: str, obj: str, src: Path, *, client: Any | None = None) -> Literal["seeded", "exists"]:
    """Upload the laptop's agent.db once; refuse if the bucket already has one."""
    try:
        store.push_db(bucket, obj, src, 0, client=client, gen_path=gen_path(src))
        _save_mark(src, snapshot_rowids(src))
        return "seeded"
    except store.ConcurrentUpdateError:
        return "exists"
