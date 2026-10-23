"""Schema migrations (v1-v3), the newer-schema guard and VACUUM, on throwaway databases."""
from __future__ import annotations

import json
import sqlite3

import pytest
from health_data import db

V0_JOURNAL = """CREATE TABLE journal (date TEXT PRIMARY KEY, mood INTEGER, energy INTEGER,
    soreness INTEGER, note TEXT, logged_at TEXT NOT NULL)"""


def _v0(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.execute(V0_JOURNAL)
    conn.execute("INSERT INTO journal VALUES ('2026-01-01', 5, 6, 7, 'a', '2026-01-01T08:00:00Z')")
    conn.execute("INSERT INTO journal VALUES ('2026-01-02', 3, 4, 2, NULL, '2026-01-02T08:00:00Z')")
    conn.commit()
    return conn


def _sub(conn, day, mood, submitted_at, status="ok", h=None, energy=5, soreness=5):
    conn.execute(
        """INSERT INTO journal_submissions (date, mood, energy, soreness, submitted_at, source,
           row_hash, imported_at, status) VALUES (?,?,?,?,?,'form',?,?,?)""",
        (day, mood, energy, soreness, submitted_at, h or f"{day}{mood}{submitted_at}{status}",
         submitted_at, status),
    )


LATEST = len(db.MIGRATIONS)


def test_migrate_from_v0_moves_journal_rows(tmp_path):
    conn = _v0(tmp_path)
    assert db.migrate(conn) == LATEST == 3
    assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST
    rows = conn.execute(
        "SELECT date, mood, source, status FROM journal_submissions ORDER BY date"
    ).fetchall()
    assert rows == [("2026-01-01", 5, "cli", "ok"), ("2026-01-02", 3, "cli", "ok")]
    assert conn.execute("SELECT date, mood FROM journal_outcome ORDER BY date").fetchall() == [
        ("2026-01-01", 5), ("2026-01-02", 3)]
    # v2 dropped the `journal` compatibility view (nothing reads it any more)
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='journal'").fetchone() is None


def test_migrate_is_idempotent(tmp_path):
    conn = _v0(tmp_path)
    assert db.migrate(conn) == LATEST
    assert db.migrate(conn) == LATEST
    assert conn.execute("SELECT COUNT(*) FROM journal_submissions").fetchone()[0] == 2


def test_migrate_fresh_db(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    assert db.migrate(conn) == LATEST
    assert conn.execute("SELECT COUNT(*) FROM journal_outcome").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0


def test_journal_submissions_reject_update_and_delete(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    db.migrate(conn)
    _sub(conn, "2026-01-01", 5, "t1")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("UPDATE journal_submissions SET mood = 9")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM journal_submissions")


def test_outcome_is_earliest_ok_submission(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    db.migrate(conn)
    _sub(conn, "2026-01-01", 1, "t0", status="invalid")
    _sub(conn, "2026-01-01", 5, "t2")
    _sub(conn, "2026-01-01", 8, "t3", status="edited")
    _sub(conn, "2026-01-01", 9, "t4")
    assert conn.execute("SELECT mood FROM journal_outcome WHERE date='2026-01-01'").fetchall() == [(5,)]


def test_v2_removes_cli_journal_writer_and_legacy_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    db.init_db()  # init_db must not recreate dropped tables
    with db.connect() as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert not names & {"journal", "journal_insert", "predictions", "signal_weights",
                        "idx_predictions_unscored"}
    assert {"journal_submissions", "journal_outcome", "raw_points", "daily_metrics"} <= names


def test_ok_row_requires_scores_1_to_10(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    db.migrate(conn)
    for bad in ({"mood": 42}, {"mood": 0}, {"energy": None}, {"soreness": 11}):
        fields = {"mood": 5, "energy": 5, "soreness": 5, **bad}
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            _sub(conn, "2026-01-01", fields["mood"], "t1", energy=fields["energy"],
                 soreness=fields["soreness"])
    _sub(conn, "2026-01-01", 42, "t2", status="invalid")  # non-ok rows may carry anything
    _sub(conn, "2026-01-01", 10, "t3", energy=1, soreness=10)
    assert conn.execute("SELECT COUNT(*) FROM journal_submissions").fetchone()[0] == 2


def test_v2_demotes_out_of_range_ok_rows_and_keeps_history(tmp_path):
    conn = _v0(tmp_path)
    conn.execute("INSERT INTO journal VALUES ('2026-01-03', 42, 4, 2, NULL, '2026-01-03T08:00:00Z')")
    conn.commit()
    db.migrate(conn)
    rows = conn.execute(
        "SELECT date, status, reason IS NOT NULL FROM journal_submissions ORDER BY date").fetchall()
    assert rows == [("2026-01-01", "ok", 0), ("2026-01-02", "ok", 0), ("2026-01-03", "invalid", 1)]
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM journal_submissions")


def test_v2_fills_civil_date_in_owner_zone(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.executescript(db.SCHEMA)  # a v1-era raw_points (no civil_date column)
    db.MIGRATIONS[0](conn)
    conn.execute("PRAGMA user_version = 1")
    point = {"heartRateVariability": {"sampleTime": {"physicalTime": "2026-10-19T23:55:00Z"}}}
    conn.execute(
        "INSERT INTO raw_points (data_type, start_time, end_time, value, source, raw_json, inserted_at)"
        " VALUES ('heart-rate-variability', '2026-10-19T23:55:00Z', '2026-10-19T23:55:00Z', 1, 'x', ?, 'n')",
        (json.dumps(point),))
    conn.execute(
        "INSERT INTO raw_points (data_type, start_time, end_time, value, source, raw_json, inserted_at)"
        " VALUES ('steps', '2026-10-19', '2026-10-19', 1, 'dailyRollUp', '{}', 'n')")
    conn.commit()
    assert db.migrate(conn) == LATEST
    got = dict(conn.execute("SELECT data_type, civil_date FROM raw_points").fetchall())
    # 23:55Z on the 19th is 05:25 IST on the 20th
    assert got == {"heart-rate-variability": "2026-10-20", "steps": "2026-10-19"}


def test_newer_schema_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {LATEST + 1}")
    conn.commit()
    with pytest.raises(db.SchemaTooNewError, match="Upgrade"):
        db.migrate(conn)
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    with pytest.raises(db.SchemaTooNewError, match=f"v{LATEST + 1}.*v{LATEST}"):
        db.init_db()
    with pytest.raises(db.SchemaTooNewError):
        with db.connect():
            pass


def test_failed_migration_rolls_back_completely(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "t.db")
    db.migrate(conn)

    def bad_step(c):
        assert c.in_transaction  # runs inside BEGIN IMMEDIATE
        c.execute("CREATE TABLE half_done (x)")
        raise RuntimeError("boom")

    monkeypatch.setattr(db, "MIGRATIONS", [*db.MIGRATIONS, bad_step])
    with pytest.raises(RuntimeError):
        db.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='half_done'").fetchone() is None


def test_migration_takes_the_write_lock_first(tmp_path):
    path = tmp_path / "t.db"
    holder = sqlite3.connect(path)
    holder.execute("BEGIN IMMEDIATE")  # another writer holds the lock
    conn = sqlite3.connect(path, timeout=0.1)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        db.migrate(conn)
    holder.rollback()
    assert db.migrate(conn) == LATEST


def test_vacuum_shrinks_after_delete(tmp_path):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [("x" * 200,)] * 10_000)
    conn.commit()
    conn.execute("DELETE FROM t")
    conn.commit()
    conn.close()
    before, after = db.vacuum(path)
    assert after < before


def test_v2_rekeys_sources_on_platform_and_drops_rename_duplicates(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.executescript(db.SCHEMA)
    db.MIGRATIONS[0](conn)
    conn.execute("PRAGMA user_version = 1")
    ins = ("INSERT INTO raw_points (data_type, start_time, end_time, value, source, raw_json, inserted_at)"
           " VALUES ('sleep', 's', 'e', ?, ?, ?, 'n')")
    for value, name in ((1, "Google Fitbit Air"), (2, "Fitbit Air")):  # same session, renamed device
        conn.execute(ins, (value, name, json.dumps(
            {"dataSource": {"platform": "FITBIT", "device": {"displayName": name}}})))
    conn.execute(ins.replace("'sleep'", "'weight'"), (3, "HEALTH_KIT", json.dumps(
        {"dataSource": {"platform": "HEALTH_KIT"}})))
    conn.commit()
    db.migrate(conn)
    assert conn.execute("SELECT data_type, value, source FROM raw_points ORDER BY data_type").fetchall() == [
        ("sleep", 2.0, "FITBIT"), ("weight", 3.0, "HEALTH_KIT")]  # newest row kept
