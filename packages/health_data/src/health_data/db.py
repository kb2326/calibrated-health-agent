"""SQLite persistence layer — the harness's memory substrate.

Sync, backfill, journal import and the agent tools read and write through here.
The base schema is created idempotently; later changes are numbered migrations
(`MIGRATIONS`, tracked in `PRAGMA user_version`), each applied inside
BEGIN IMMEDIATE. A database whose schema is newer than this code is refused
rather than written with older code.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from health_core.settings import get_settings

from health_data import civil

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
    source TEXT NOT NULL DEFAULT '',
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

CREATE INDEX IF NOT EXISTS idx_daily_metrics_type_date
    ON daily_metrics(data_type, date);
CREATE INDEX IF NOT EXISTS idx_raw_points_type_start
    ON raw_points(data_type, start_time);

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


# v2: the Google Form is the only journal writer (the INSERT-into-view path and the
# `journal` compatibility view go), ok rows must carry 1..10 scores, the retired learning
# loop's tables are dropped, listed raw_points are re-keyed on their stable platform source
# (see point_source), and raw_points gains the owner-zone civil day each row belongs to
# (rule: health_data.civil).
_SCORES_OK = ("mood BETWEEN 1 AND 10 AND energy BETWEEN 1 AND 10 "
              "AND soreness BETWEEN 1 AND 10")

_V2_JOURNAL = f"""
CREATE TABLE journal_submissions_v2 (
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
    UNIQUE(row_hash),
    CHECK(status <> 'ok' OR COALESCE({_SCORES_OK}, 0))
);

INSERT INTO journal_submissions_v2
SELECT id, date, mood, energy, soreness, note, tags, submitted_at, source, sheet_row,
       row_hash, imported_at,
       CASE WHEN status = 'ok' AND NOT COALESCE({_SCORES_OK}, 0) THEN 'invalid' ELSE status END,
       response_id,
       CASE WHEN status = 'ok' AND NOT COALESCE({_SCORES_OK}, 0)
            THEN 'score out of range 1..10 (schema v2)' ELSE reason END
FROM journal_submissions ORDER BY id;

DROP TABLE journal_submissions;

ALTER TABLE journal_submissions_v2 RENAME TO journal_submissions;

CREATE TRIGGER journal_submissions_no_update
BEFORE UPDATE ON journal_submissions
BEGIN SELECT RAISE(ABORT, 'journal_submissions is append-only'); END;

CREATE TRIGGER journal_submissions_no_delete
BEFORE DELETE ON journal_submissions
BEGIN SELECT RAISE(ABORT, 'journal_submissions is append-only'); END;

CREATE VIEW journal_outcome AS
SELECT s.date, s.mood, s.energy, s.soreness, s.id AS submission_id
FROM journal_submissions s
WHERE s.status = 'ok'
  AND s.id = (SELECT s2.id FROM journal_submissions s2
              WHERE s2.date = s.date AND s2.status = 'ok'
              ORDER BY s2.submitted_at, s2.id LIMIT 1);
"""


def point_source(point: dict) -> str:
    """The stable source key of a listed point: its platform (FITBIT, HEALTH_KIT, ...).

    It is part of raw_points' unique key, so it must not change when the same point is
    fetched again. Device display names do change upstream ("Google Fitbit Air" became
    "Fitbit Air"), which duplicated every refetched point; the platform does not. The
    device name stays available in raw_json.
    """
    ds = point.get("dataSource") or {}
    return str(ds.get("platform") or (ds.get("device") or {}).get("displayName") or "unknown")


def rekey_sources(conn: sqlite3.Connection) -> int:
    """Re-key listed raw_points on `point_source`, keeping the newest row per key.

    Returns how many duplicate rows were removed.
    """
    rows = conn.execute(
        "SELECT id, data_type, start_time, end_time, source, raw_json FROM raw_points "
        "WHERE source IS NOT 'dailyRollUp' ORDER BY id DESC"
    ).fetchall()
    seen: set[tuple] = set()
    drop: list[tuple[int]] = []
    rename: list[tuple[str, int]] = []
    for rid, data_type, start, end, source, raw_json in rows:
        try:
            point = json.loads(raw_json)
        except ValueError:
            point = {}
        key_source = point_source(point) if point.get("dataSource") else source
        key = (data_type, start, end, key_source)
        if key in seen:
            drop.append((rid,))
            continue
        seen.add(key)
        if key_source != source:
            rename.append((key_source, rid))
    conn.executemany("DELETE FROM raw_points WHERE id=?", drop)
    # Two phases so no intermediate state can collide on the unique key.
    conn.executemany("UPDATE raw_points SET source='~rekey~' || id WHERE id=?", [(r,) for _, r in rename])
    conn.executemany("UPDATE raw_points SET source=? WHERE id=?", rename)
    return len(drop)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def raw_civil_date(data_type: str, start_time: str, source: str | None, raw_json: str) -> str | None:
    """The civil day of a stored raw_points row (rollup rows already store their day)."""
    if source == "dailyRollUp":
        return start_time[:10]
    try:
        point = json.loads(raw_json)
    except ValueError:
        point = {}
    return civil.day_of_point(data_type, point) or civil.day_of_instant(start_time)


def fill_civil_dates(conn: sqlite3.Connection, data_type: str | None = None) -> None:
    """(Re)compute raw_points.civil_date for every row (of one type, if given)."""
    sql = "SELECT id, data_type, start_time, source, raw_json FROM raw_points"
    rows = conn.execute(sql + (" WHERE data_type=?" if data_type else ""),
                        (data_type,) if data_type else ()).fetchall()
    conn.executemany(
        "UPDATE raw_points SET civil_date=? WHERE id=?",
        [(raw_civil_date(dt, st, src, rj), rid) for rid, dt, st, src, rj in rows],
    )


def _migrate_v2(conn: sqlite3.Connection) -> None:
    for stmt in (
        "DROP TRIGGER IF EXISTS journal_insert",
        "DROP VIEW IF EXISTS journal",
        "DROP VIEW IF EXISTS journal_outcome",
        "DROP TRIGGER IF EXISTS journal_submissions_no_update",
        "DROP TRIGGER IF EXISTS journal_submissions_no_delete",
        "DROP INDEX IF EXISTS idx_predictions_unscored",
        "DROP TABLE IF EXISTS predictions",
        "DROP TABLE IF EXISTS signal_weights",
    ):
        conn.execute(stmt)
    for stmt in _split(_V2_JOURNAL):
        conn.execute(stmt)
    if _is_table(conn, "raw_points"):
        if "civil_date" not in _columns(conn, "raw_points"):
            conn.execute("ALTER TABLE raw_points ADD COLUMN civil_date TEXT")
        rekey_sources(conn)
        fill_civil_dates(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_raw_points_type_civil ON raw_points(data_type, civil_date)"
        )


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


# v3: daily_metrics records which source its value came from, and types with a source
# preference (config/health.yaml `sources`) are rebuilt so no day mixes sources (Fitbit
# RMSSD with Apple SDNN). The forecast ledger's evidence tables arrive here too; all four
# are append-only (health_ledger writes them; nothing ever edits or deletes a row).
# (Fresh databases already get the daily_metrics column from SCHEMA; older ones gain it here.)
_V3_DDL = """
ALTER TABLE daily_metrics ADD COLUMN source TEXT NOT NULL DEFAULT '';
"""

_LEDGER_TABLES = ("snapshots", "forecasts", "ledger", "scores")

_V3_LEDGER = """
CREATE TABLE snapshots (
    day TEXT PRIMARY KEY,
    snapshot_json TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    locked_at TEXT NOT NULL,
    missing_json TEXT NOT NULL
);

CREATE TABLE forecasts (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    forecaster TEXT NOT NULL,
    target TEXT NOT NULL CHECK(target IN ('mood','energy','soreness')),
    probs_json TEXT,
    abstain_reason TEXT,
    locked_at TEXT NOT NULL,
    UNIQUE(day, forecaster, target),
    CHECK((probs_json IS NULL) <> (abstain_reason IS NULL))
);

CREATE TABLE ledger (
    seq INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('plan','lock','outcome','void','no_outcome')),
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE(day, kind)
);

CREATE TABLE scores (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    forecaster TEXT NOT NULL,
    target TEXT NOT NULL,
    outcome INT NOT NULL,
    rps REAL NOT NULL,
    log_score REAL NOT NULL,
    scored_at TEXT NOT NULL,
    UNIQUE(day, forecaster, target)
);
""" + "".join(f"""
CREATE TRIGGER {t}_no_update BEFORE UPDATE ON {t}
BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;

CREATE TRIGGER {t}_no_delete BEFORE DELETE ON {t}
BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;
""" for t in _LEDGER_TABLES)


def _migrate_v3(conn: sqlite3.Connection) -> None:
    from health_data import sync  # lazy: sync imports this module

    if _is_table(conn, "daily_metrics") and "source" not in _columns(conn, "daily_metrics"):
        for stmt in _split(_V3_DDL):
            conn.execute(stmt)
    if _is_table(conn, "raw_points") and _is_table(conn, "daily_metrics"):
        for data_type in sync.CONFIG["data_types"]:
            if sync.source_preference(data_type):
                sync.rebuild_daily(conn, data_type)
    for stmt in _split(_V3_LEDGER):
        conn.execute(stmt)


# v4: the agent layer's evidence (Phase 3). Append-only like the ledger: hypotheses and
# their receipts are what forecaster 7 read, and its notes are hashed into the chain.
_AGENT_TABLES = ("receipts", "hypotheses", "hypothesis_status", "lock_notes", "agent_runs")

_V4_AGENT = """
CREATE TABLE receipts (
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

CREATE TABLE hypotheses (
    id TEXT PRIMARY KEY,
    created_day TEXT NOT NULL,
    statement TEXT NOT NULL,
    target TEXT NOT NULL CHECK(target IN ('mood','energy','soreness')),
    direction TEXT NOT NULL CHECK(direction IN ('lower','higher')),
    condition_code TEXT NOT NULL,
    in_sample_json TEXT NOT NULL,
    receipt_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE hypothesis_status (
    id INTEGER PRIMARY KEY,
    hypothesis_id TEXT NOT NULL,
    day TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('open','supported','refuted','retired')),
    n_cond INT NOT NULL,
    n_other INT NOT NULL,
    effect REAL,
    p_value REAL,
    receipt_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(hypothesis_id, day)
);

CREATE TABLE lock_notes (
    day TEXT NOT NULL,
    forecaster TEXT NOT NULL,
    notes_json TEXT NOT NULL,
    notes_hash TEXT NOT NULL,
    PRIMARY KEY(day, forecaster)
);

CREATE TABLE agent_runs (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('investigate','forecast7')),
    covered_days_json TEXT NOT NULL,
    calls INT NOT NULL,
    input_tokens INT NOT NULL,
    output_tokens INT NOT NULL,
    usd REAL NOT NULL,
    outcome TEXT NOT NULL,
    created_at TEXT NOT NULL
);
""" + "".join(f"""
CREATE TRIGGER {t}_no_update BEFORE UPDATE ON {t}
BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;

CREATE TRIGGER {t}_no_delete BEFORE DELETE ON {t}
BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;
""" for t in _AGENT_TABLES)


def _migrate_v4(conn: sqlite3.Connection) -> None:
    for stmt in _split(_V4_AGENT):
        conn.execute(stmt)


MIGRATIONS = [_migrate_v1, _migrate_v2, _migrate_v3, _migrate_v4]


class SchemaTooNewError(RuntimeError):
    """The database was written by newer code; this code must not open it."""


def _user_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def check_schema(conn: sqlite3.Connection, path: object = None) -> int:
    """Return user_version; raise SchemaTooNewError if it is newer than MIGRATIONS."""
    version = _user_version(conn)
    known = len(MIGRATIONS)
    if version > known:
        where = f"{path} " if path else ""
        raise SchemaTooNewError(
            f"database {where}has schema v{version}, newer than this code supports (v{known}). "
            "Upgrade before opening it: `git pull && uv sync --all-packages` locally, or rebuild "
            "and redeploy the job image. Older code must never write a newer database."
        )
    return version


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending schema migrations; return the resulting user_version.

    Each step runs inside BEGIN IMMEDIATE (the write lock is taken before the version is
    re-read, so two processes can never both apply the same step) and commits together
    with its `PRAGMA user_version` bump; a failing step rolls back completely.
    """
    version = check_schema(conn)
    for target, step in enumerate(MIGRATIONS, start=1):
        if version >= target:
            continue
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        try:
            version = _user_version(conn)  # another writer may have migrated meanwhile
            if version < target:
                step(conn)
                conn.execute(f"PRAGMA user_version = {target}")
                version = target
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
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
    try:
        check_schema(conn, DB_PATH)
    except BaseException:
        conn.close()
        raise
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
