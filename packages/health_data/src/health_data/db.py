"""SQLite persistence layer — the harness's memory substrate.

Every loop script (sync/analyze/correlate/digest) reads and writes through
here instead of re-querying the API or holding state only in an LLM context
window. Schema is created idempotently on first use.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime

from health_core.settings import get_settings

DB_PATH = get_settings().db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_type TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    value REAL,
    unit TEXT,
    source TEXT,
    raw_json TEXT NOT NULL,
    inserted_at TEXT NOT NULL,
    UNIQUE(data_type, start_time, end_time, source)
);

CREATE TABLE IF NOT EXISTS sync_state (
    data_type TEXT PRIMARY KEY,
    cursor_time TEXT NOT NULL,
    last_synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_metrics (
    date TEXT NOT NULL,
    data_type TEXT NOT NULL,
    agg_value REAL NOT NULL,
    n_points INTEGER NOT NULL,
    PRIMARY KEY (date, data_type)
);

CREATE TABLE IF NOT EXISTS journal (
    date TEXT PRIMARY KEY,
    mood INTEGER,
    energy INTEGER,
    soreness INTEGER,
    note TEXT,
    logged_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    data_type TEXT NOT NULL,
    value REAL,
    baseline_mean REAL,
    baseline_std REAL,
    z_score REAL,
    severity TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    UNIQUE(date, data_type)
);

CREATE TABLE IF NOT EXISTS correlations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_a TEXT NOT NULL,
    metric_b TEXT NOT NULL,
    lag_days INTEGER NOT NULL,
    r REAL NOT NULL,
    n INTEGER NOT NULL,
    computed_at TEXT NOT NULL,
    UNIQUE(metric_a, metric_b, lag_days)
);

-- The learning loop. An anomaly is not just a finding, it is a claim about
-- what tomorrow will feel like; recording it as a dated prediction lets the
-- next journal entry score it. Signals that never predict correctly for
-- this person get demoted, which is what turns a static threshold in YAML
-- into a parameter learned from their own history.
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    made_on TEXT NOT NULL,          -- date the prediction was emitted
    signal TEXT NOT NULL,           -- metric that triggered it
    signal_date TEXT NOT NULL,      -- day the signal was observed
    signal_z REAL NOT NULL,
    target TEXT NOT NULL,           -- journal field it predicts
    target_date TEXT NOT NULL,      -- day the prediction is about
    lag_days INTEGER NOT NULL,
    expected_direction TEXT NOT NULL,   -- 'low' or 'high'
    actual_value REAL,              -- filled by learn.py once known
    hit INTEGER,                    -- 1 / 0 / NULL while unscored
    scored_at TEXT,
    UNIQUE(signal, signal_date, target, lag_days)
);

CREATE TABLE IF NOT EXISTS signal_weights (
    signal TEXT NOT NULL,
    target TEXT NOT NULL,
    lag_days INTEGER NOT NULL,
    n_scored INTEGER NOT NULL DEFAULT 0,
    n_hit INTEGER NOT NULL DEFAULT 0,
    hit_rate REAL,
    weight REAL NOT NULL DEFAULT 1.0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (signal, target, lag_days)
);

CREATE INDEX IF NOT EXISTS idx_daily_metrics_type_date
    ON daily_metrics(data_type, date);
CREATE INDEX IF NOT EXISTS idx_raw_points_type_start
    ON raw_points(data_type, start_time);
CREATE INDEX IF NOT EXISTS idx_predictions_unscored
    ON predictions(target_date) WHERE hit IS NULL;

CREATE TABLE IF NOT EXISTS stage_output (
    stage TEXT NOT NULL,
    run_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (stage, run_key)
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets analysis read while an ingest is mid-write. Without it a long
    # backfill holds an exclusive lock and every reader gets "database is
    # locked" for the duration.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def write_stage_output(stage: str, run_key: str, payload: dict) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO stage_output (stage, run_key, payload_json, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(stage, run_key) DO UPDATE SET
                 payload_json=excluded.payload_json, created_at=excluded.created_at""",
            (stage, run_key, json.dumps(payload), now_iso()),
        )


def read_stage_output(stage: str, run_key: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT payload_json FROM stage_output WHERE stage=? AND run_key=?",
            (stage, run_key),
        ).fetchone()
        return json.loads(row[0]) if row else None


if __name__ == "__main__":
    init_db()
    print(f"Initialized schema at {DB_PATH}")
