"""Receipts: the code, data fingerprint and output behind every number the agent states.

A receipt's id is a hash of its content (kind, code, data hash, as-of day, output), so the
same computation on the same data always gets the same id and is stored once. Chat
receipts live in the laptop's `agent.db`; the investigator's live in `health.db` (pushed
with the job), because the hypotheses that cite them are part of the ledger's evidence.
`rerun` (added with the tools that produce receipts) reproduces a receipt's value.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from health_data import db
from health_ledger.features import canonical, sha256

from . import agent_db

SANDBOX = "sandbox-subprocess/1"
SQLITE = "sqlite-ro/1"


@dataclass(frozen=True)
class Receipt:
    id: str
    kind: str
    code: str
    data_hash: str
    as_of: str
    output: Any
    executor: str
    context: str
    created_at: str


def record(conn: sqlite3.Connection, *, kind: str, code: str, data_hash: str, as_of: str,
           output: Any, executor: str, context: str) -> str:
    rid = "r-" + sha256(canonical([kind, code, data_hash, as_of, output]))[:10]
    conn.execute("INSERT OR IGNORE INTO receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (rid, kind, code, data_hash, as_of, canonical(output), executor, context,
                  db.utc_stamp()))
    return rid


def _row(conn: sqlite3.Connection, receipt_id: str) -> Receipt | None:
    row = conn.execute("SELECT id, kind, code, data_hash, as_of, output_json, executor, context,"
                       " created_at FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
    if row is None:
        return None
    return Receipt(*row[:5], json.loads(row[5]), *row[6:])  # type: ignore[arg-type]


def get(receipt_id: str) -> tuple[Receipt, str] | None:
    """The receipt and where it was found: "chat" (agent.db) or "investigator" (health.db)."""
    with agent_db.connect() as conn:
        found = _row(conn, receipt_id)
    if found is not None:
        return found, "chat"
    if not db.DB_PATH.exists():
        return None
    conn = sqlite3.connect(f"file:{db.DB_PATH}?mode=ro", uri=True)
    try:
        found = _row(conn, receipt_id)
    except sqlite3.OperationalError:  # a database from before schema v4
        found = None
    finally:
        conn.close()
    return (found, "investigator") if found is not None else None
