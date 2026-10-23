"""The ledger's hash chain: each entry commits to its payload and to every entry before it.

    payload_hash = sha256(canonical(payload))
    entry_hash   = sha256(prev_hash + "|" + day + "|" + kind + "|" + payload_hash)

The first entry is always the pre-registered analysis plan (kind `plan`, day
`0000-00-00`), whose payload is the sha256 of the plan document. Changing any past
payload, or the plan, changes every later entry_hash, and the daily entry hashes are
published to the public log, so a rewrite cannot go unnoticed. `append` does not commit:
callers write an entry in the same transaction as the rows it covers.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from health_data import db

from health_ledger.features import canonical, sha256

GENESIS_PREV = "0" * 64
PLAN_DAY = "0000-00-00"


def _entry_hash(prev: str, day: str, kind: str, payload_hash: str) -> str:
    return sha256(f"{prev}|{day}|{kind}|{payload_hash}")


def append(conn: sqlite3.Connection, day: str, kind: str, payload: dict) -> str:
    row = conn.execute("SELECT entry_hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
    prev = row[0] if row else GENESIS_PREV
    payload_json = canonical(payload)
    payload_hash = sha256(payload_json)
    entry = _entry_hash(prev, day, kind, payload_hash)
    conn.execute(
        """INSERT INTO ledger (day, kind, payload_json, payload_hash, prev_hash, entry_hash,
                               created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (day, kind, payload_json, payload_hash, prev, entry, db.utc_stamp()))
    return entry


def verify(conn: sqlite3.Connection) -> list[str]:
    """One message per broken entry; empty when the whole chain recomputes and links."""
    problems = []
    prev = GENESIS_PREV
    rows = conn.execute("SELECT seq, day, kind, payload_json, payload_hash, prev_hash, entry_hash "
                        "FROM ledger ORDER BY seq")
    for i, (seq, day, kind, payload_json, payload_hash, prev_hash, entry) in enumerate(rows):
        if i == 0 and kind != "plan":
            problems.append(f"seq {seq}: the first entry must be the analysis plan")
        if sha256(canonical(json.loads(payload_json))) != payload_hash:
            problems.append(f"seq {seq}: payload does not match its hash")
        if prev_hash != prev:
            problems.append(f"seq {seq}: prev_hash does not link to the entry before")
        if _entry_hash(prev_hash, day, kind, payload_hash) != entry:
            problems.append(f"seq {seq}: entry_hash does not recompute")
        prev = entry
    return problems


def ensure_plan_hash(conn: sqlite3.Connection, plan_sha256: str) -> None:
    """Append the genesis `plan` entry if the chain has none; commits."""
    if conn.execute("SELECT 1 FROM ledger WHERE kind = 'plan'").fetchone() is None:
        append(conn, PLAN_DAY, "plan", {"analysis_plan_sha256": plan_sha256})
        conn.commit()


def plan_sha256(plan_path: Path) -> str:
    """sha256 of the plan text with LF line endings, so a Windows checkout (CRLF) and a
    Linux one hash the same and anyone can verify the published genesis entry."""
    return sha256(Path(plan_path).read_bytes().decode("utf-8").replace("\r\n", "\n"))


def ensure_plan(conn: sqlite3.Connection, plan_path: Path) -> None:
    ensure_plan_hash(conn, plan_sha256(plan_path))
