"""Shared synthetic fixtures for the ledger tests: an in-memory-shaped temp database."""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from health_data import db


def make_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(db.SCHEMA)  # what db.init_db does, on a path of our own
    db.migrate(conn)
    return conn


def metric(conn: sqlite3.Connection, day: date | str, data_type: str, value: float,
           source: str = "") -> None:
    conn.execute(
        "INSERT INTO daily_metrics (date, data_type, agg_value, n_points, source) "
        "VALUES (?, ?, ?, 1, ?)", (str(day), data_type, value, source))


def journal(conn: sqlite3.Connection, day: date | str, mood: int, energy: int, soreness: int,
            submitted_at: str | None = None, status: str = "ok", *,
            tags: list[str] | None = None, note: str | None = None) -> int:
    """Append one Form submission; returns its id. submitted_at defaults to 20:00 IST of day."""
    stamp = submitted_at or f"{day}T14:30:00.000000Z"
    cur = conn.execute(
        """INSERT INTO journal_submissions
           (date, mood, energy, soreness, note, tags, submitted_at, source, sheet_row,
            row_hash, imported_at, status, response_id, reason)
           VALUES (?,?,?,?,?,?,?, 'form', NULL, ?, ?, ?, ?, NULL)""",
        (str(day), mood, energy, soreness, note, json.dumps(tags or []), stamp, f"hash-{day}-{stamp}", stamp, status,
         f"r-{day}-{stamp}"))
    return int(cur.lastrowid or 0)
