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


def rows_hash(rows: Any) -> str:
    """A SQL receipt's data fingerprint is the hash of the rows it returned."""
    return sha256(canonical(rows))


def rerun(receipt_id: str) -> dict:
    """Re-run a receipt's code on the current local data and compare.

    `matches`: same value. `data_changed`: the data the code read differs from when the
    receipt was made (a late sync or backfill), so a different value is expected.
    """
    from datetime import date

    from . import sqlguard, tools

    found = get(receipt_id)
    if found is None:
        return {"id": receipt_id, "error": "no such receipt"}
    receipt, _ = found
    if receipt.kind == "sql":
        conn, denied = sqlguard.guarded_connect(db.DB_PATH)
        try:
            new = [dict(r) for r in conn.execute(receipt.code).fetchmany(tools.MAX_ROWS)]
        except sqlite3.Error as exc:
            return {"id": receipt_id, "error": sqlguard.explain(denied, exc)}
        finally:
            conn.close()
        changed = rows_hash(new) != receipt.data_hash
        return {"id": receipt_id, "matches": new == receipt.output, "data_changed": changed,
                "old": receipt.output, "new": new}
    with tools._ro_connect() as conn:
        out = tools.run_python_on(conn, receipt.code, date.fromisoformat(receipt.as_of),
                                  investigator=receipt.context == "investigator")
    if "error" in out:
        return {"id": receipt_id, "error": out["error"]}
    return {"id": receipt_id, "matches": out["result"] == receipt.output,
            "data_changed": out["data_hash"] != receipt.data_hash,
            "old": receipt.output, "new": out["result"]}
