"""Laptop-only agent state in `data/agent.db`: chat receipts, memory and chat spend.

Never pushed to the bucket. Unlike `health.db`'s agent tables these rows are the owner's to
edit (forget a fact, close it), so they are not append-only.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from health_core.settings import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('python','sql')),
    code TEXT NOT NULL,
    data_hash TEXT NOT NULL,
    as_of TEXT NOT NULL,
    output_json TEXT NOT NULL,
    executor TEXT NOT NULL,
    context TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    day TEXT,
    text TEXT NOT NULL,
    vector BLOB,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_usage (
    id INTEGER PRIMARY KEY,
    month TEXT NOT NULL,
    input_tokens INT NOT NULL,
    output_tokens INT NOT NULL,
    usd REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes_seen (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = get_settings().agent_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()
