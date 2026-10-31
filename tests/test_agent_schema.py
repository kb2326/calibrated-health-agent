"""Schema v4: append-only agent tables in health.db, and the laptop-only agent.db."""
from __future__ import annotations

import sqlite3

import pytest
from health_agents import agent_db
from health_core.settings import Settings
from health_data import db
from ledger_fixtures import make_db

V4_TABLES = ("receipts", "hypotheses", "hypothesis_status", "lock_notes", "agent_runs")

ROWS = {
    "receipts": "INSERT INTO receipts VALUES ('r-1','sql','SELECT 1','h','2026-10-22','[1]','sqlite-ro/1','chat','t')",
    "hypotheses": "INSERT INTO hypotheses VALUES ('h-1','2026-10-22','s','energy','lower','c','{}','[]','t')",
    "hypothesis_status": "INSERT INTO hypothesis_status (hypothesis_id, day, status, n_cond, n_other, effect, p_value, receipt_id, created_at) VALUES ('h-1','2026-10-22','open',1,1,0,1,NULL,'t')",
    "lock_notes": "INSERT INTO lock_notes VALUES ('2026-10-22','f','[]','x')",
    "agent_runs": "INSERT INTO agent_runs (day, kind, covered_days_json, calls, input_tokens, output_tokens, usd, outcome, created_at) VALUES ('2026-10-22','investigate','[]',0,0,0,0,'done','t')",
}


def test_v4_creates_agent_tables(tmp_path):
    conn = make_db(tmp_path / "h.db")
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(V4_TABLES) <= names
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5


@pytest.mark.parametrize("table", V4_TABLES)
def test_v4_agent_tables_are_append_only(tmp_path, table):
    conn = make_db(tmp_path / "h.db")
    conn.execute(ROWS[table])
    conn.commit()
    for stmt in (f"UPDATE {table} SET rowid = rowid", f"DELETE FROM {table}"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(stmt)


def test_retired_is_a_valid_status(tmp_path):
    conn = make_db(tmp_path / "h.db")
    conn.execute(ROWS["hypothesis_status"].replace("'open'", "'retired'"))


def test_v3_database_migrates_to_v4_keeping_rows(tmp_path):
    conn = sqlite3.connect(tmp_path / "h.db")
    conn.executescript(db.SCHEMA)
    for step in db.MIGRATIONS[:3]:
        step(conn)
    conn.execute("PRAGMA user_version = 3")
    conn.execute("INSERT INTO daily_metrics (date, data_type, agg_value, n_points, source) "
                 "VALUES ('2026-10-01','steps',1,1,'')")
    conn.commit()
    assert db.migrate(conn) == 5
    assert conn.execute("SELECT COUNT(*) FROM daily_metrics").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0


def test_agent_db_is_created_on_first_connect(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_db, "get_settings",
                        lambda: Settings.model_validate({"data_dir": tmp_path}))
    with agent_db.connect() as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"receipts", "facts", "episodes", "chat_usage", "notes_seen"} <= names
    assert (tmp_path / "agent.db").exists()
