"""SQLite persistence layer — the harness's memory substrate.

Every loop script (sync/analyze/correlate/digest) reads and writes through
here instead of re-querying the API or holding state only in an LLM context
window. Schema is created idempotently on first use.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

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


def utc_stamp(moment: datetime | None = None) -> str:
    """UTC ISO-8601 with fixed width (microseconds, `Z`), so text order is time order."""
    moment = moment or datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("utc_stamp needs a timezone-aware datetime")
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def journal_row_hash(
    day: str, mood: int | None, energy: int | None, soreness: int | None,
    note: str | None, submitted_at: str, source: str,
) -> str:
    """Content hash of one journal submission (submitted_at makes repeats distinct)."""
    payload = json.dumps([day, mood, energy, soreness, note, submitted_at, source])
    return hashlib.sha256(payload.encode()).hexdigest()


_V1_TABLES = """
CREATE TABLE journal_submissions (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    mood INT,
    energy INT,
    soreness INT,
    note TEXT,
    tags TEXT,
    submitted_at TEXT NOT NULL,
    source TEXT NOT NULL,
    sheet_row INT,
    row_hash TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ok','late','edited','invalid')),
    response_id TEXT,
    reason TEXT,
    UNIQUE(row_hash)
);

CREATE TRIGGER journal_submissions_no_update
BEFORE UPDATE ON journal_submissions
BEGIN SELECT RAISE(ABORT, 'journal_submissions is append-only'); END;

CREATE TRIGGER journal_submissions_no_delete
BEFORE DELETE ON journal_submissions
BEGIN SELECT RAISE(ABORT, 'journal_submissions is append-only'); END;

CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    display_name TEXT,
    raw_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
"""

# Views are created after the legacy table is gone (they share its name).
_V1_VIEWS = """
CREATE VIEW journal_outcome AS
SELECT s.date, s.mood, s.energy, s.soreness, s.id AS submission_id
FROM journal_submissions s
WHERE s.status = 'ok'
  AND s.id = (SELECT s2.id FROM journal_submissions s2
              WHERE s2.date = s.date AND s2.status = 'ok'
              ORDER BY s2.submitted_at, s2.id LIMIT 1);

-- Compatibility view: carried readers still query `journal`.
CREATE VIEW journal AS
SELECT o.date, o.mood, o.energy, o.soreness, s.note, s.submitted_at AS logged_at
FROM journal_outcome o JOIN journal_submissions s ON s.id = o.submission_id;

-- Compatibility writer: an insert into `journal` appends a submission.
CREATE TRIGGER journal_insert INSTEAD OF INSERT ON journal
BEGIN
    INSERT INTO journal_submissions
        (date, mood, energy, soreness, note, submitted_at, source, row_hash,
         imported_at, status)
    VALUES (NEW.date, NEW.mood, NEW.energy, NEW.soreness, NEW.note,
            COALESCE(NEW.logged_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), 'cli',
            'view:' || lower(hex(randomblob(16))),
            strftime('%Y-%m-%dT%H:%M:%fZ','now'), 'ok');
END;
"""


def _is_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _migrate_v1(conn: sqlite3.Connection) -> None:
    legacy = []
    if _is_table(conn, "journal"):
        legacy = conn.execute(
            "SELECT date, mood, energy, soreness, note, logged_at FROM journal ORDER BY date"
        ).fetchall()
    conn.execute("BEGIN")
    try:
        for stmt in _split(_V1_TABLES):
            conn.execute(stmt)
        imported = now_iso()
        for day, mood, energy, soreness, note, logged_at in legacy:
            conn.execute(
                """INSERT INTO journal_submissions
                   (date, mood, energy, soreness, note, submitted_at, source,
                    row_hash, imported_at, status)
                   VALUES (?,?,?,?,?,?, 'cli', ?, ?, 'ok')""",
                (day, mood, energy, soreness, note, logged_at,
                 journal_row_hash(day, mood, energy, soreness, note, logged_at, "cli"),
                 imported),
            )
        if _is_table(conn, "journal"):
            conn.execute("DROP TABLE journal")
        for stmt in _split(_V1_VIEWS):
            conn.execute(stmt)
        conn.execute("PRAGMA user_version = 1")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _split(script: str) -> list[str]:
    """Split a script into statements (triggers contain inner semicolons)."""
    out, buf = [], ""
    for line in script.splitlines():
        if line.strip().startswith("--"):
            continue
        buf += line + chr(10)
        if sqlite3.complete_statement(buf):
            out.append(buf.strip())
            buf = ""
    return out


MIGRATIONS = [_migrate_v1]


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending schema migrations; return the resulting user_version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for target, step in enumerate(MIGRATIONS, start=1):
        if version < target:
            step(conn)
            version = target
    return version


def vacuum(path: Path) -> tuple[int, int]:
    """VACUUM the DB at `path`; return (bytes before, bytes after)."""
    path = Path(path)
    before = path.stat().st_size
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    finally:
        conn.close()
    return before, path.stat().st_size


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
        migrate(conn)


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
