"""Schema v3 ledger tables: append-only evidence, one forecast shape per row."""
from __future__ import annotations

import sqlite3

import pytest
from health_data import db


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "t.db")
    db.migrate(c)
    yield c
    c.close()


def _seed(c: sqlite3.Connection) -> None:
    c.execute("INSERT INTO snapshots VALUES ('2026-10-23', '{}', 'h', 't', '[]')")
    c.execute("INSERT INTO forecasts (day, forecaster, target, probs_json, abstain_reason, locked_at) "
              "VALUES ('2026-10-23', 'climatology', 'energy', '[0.1]', NULL, 't')")
    c.execute("INSERT INTO ledger (day, kind, payload_json, payload_hash, prev_hash, entry_hash, created_at) "
              "VALUES ('2026-10-23', 'lock', '{}', 'p', 'z', 'e', 't')")
    c.execute("INSERT INTO scores (day, forecaster, target, outcome, rps, log_score, scored_at) "
              "VALUES ('2026-10-23', 'climatology', 'energy', 5, 0.1, 1.2, 't')")
    c.commit()


@pytest.mark.parametrize("table", ["snapshots", "forecasts", "ledger", "scores"])
def test_ledger_tables_are_append_only(conn, table):
    _seed(conn)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(f"UPDATE {table} SET day = '2026-10-24'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(f"DELETE FROM {table}")


def test_forecast_is_probs_xor_abstain(conn):
    sql = ("INSERT INTO forecasts (day, forecaster, target, probs_json, abstain_reason, locked_at) "
           "VALUES ('2026-10-23', 'x', 'mood', ?, ?, 't')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, ("[0.1]", "no data"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (None, None))
    conn.execute(sql, (None, "no data"))
    with pytest.raises(sqlite3.IntegrityError):  # unknown target
        conn.execute(sql.replace("'mood'", "'sleep'"), ("[0.1]", None))


def test_one_ledger_entry_per_day_and_kind(conn):
    sql = ("INSERT INTO ledger (day, kind, payload_json, payload_hash, prev_hash, entry_hash, created_at) "
           "VALUES ('2026-10-23', ?, '{}', 'p', 'z', ?, 't')")
    conn.execute(sql, ("lock", "e1"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, ("lock", "e2"))
    with pytest.raises(sqlite3.IntegrityError):  # unknown kind
        conn.execute(sql, ("guess", "e3"))
