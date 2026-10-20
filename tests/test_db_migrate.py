"""Schema migration v1 and VACUUM, on throwaway databases."""
from __future__ import annotations

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


def _sub(conn, day, mood, submitted_at, status="ok", h=None):
    conn.execute(
        """INSERT INTO journal_submissions (date, mood, submitted_at, source, row_hash,
           imported_at, status) VALUES (?,?,?,'sheet',?,?,?)""",
        (day, mood, submitted_at, h or f"{day}{mood}{submitted_at}{status}", submitted_at, status),
    )


def test_migrate_from_v0_moves_journal_rows(tmp_path):
    conn = _v0(tmp_path)
    assert db.migrate(conn) == 1
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    rows = conn.execute(
        "SELECT date, mood, source, status FROM journal_submissions ORDER BY date"
    ).fetchall()
    assert rows == [("2026-01-01", 5, "cli", "ok"), ("2026-01-02", 3, "cli", "ok")]
    assert conn.execute("SELECT date, mood FROM journal_outcome ORDER BY date").fetchall() == [
        ("2026-01-01", 5), ("2026-01-02", 3)]
    # carried readers still see a `journal` relation, now a view
    assert conn.execute("SELECT type FROM sqlite_master WHERE name='journal'").fetchone()[0] == "view"
    assert conn.execute("SELECT note, logged_at FROM journal WHERE date='2026-01-01'").fetchone() == (
        "a", "2026-01-01T08:00:00Z")


def test_migrate_is_idempotent(tmp_path):
    conn = _v0(tmp_path)
    assert db.migrate(conn) == 1
    assert db.migrate(conn) == 1
    assert conn.execute("SELECT COUNT(*) FROM journal_submissions").fetchone()[0] == 2


def test_migrate_fresh_db(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    assert db.migrate(conn) == 1
    assert conn.execute("SELECT COUNT(*) FROM journal").fetchone()[0] == 0
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


def test_journal_insert_appends_submission(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    with db.connect() as conn:
        conn.execute("INSERT OR REPLACE INTO journal (date, mood, logged_at) VALUES ('2026-02-01', 4, 'x')")
        conn.execute("INSERT OR REPLACE INTO journal (date, mood, logged_at) VALUES ('2026-02-01', 9, 'y')")
        assert conn.execute("SELECT COUNT(*) FROM journal_submissions").fetchone()[0] == 2
        assert conn.execute("SELECT mood FROM journal").fetchall() == [(4,)]


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
