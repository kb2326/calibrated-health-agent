"""Daily values come from one preferred source, never a pool of RMSSD (Fitbit) and SDNN (Apple)."""
from __future__ import annotations

import sqlite3

import pytest
from health_data import db, sync

DAY = "2026-10-20"


@pytest.fixture
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    return tmp_path / "t.db"


def _config(**types: dict) -> dict:
    return {"initial_backfill_days": 5,
            "data_types": {t: {"scope": "x", "agg": "mean", **c} for t, c in types.items()}}


def _raw(conn, data_type, value, source, n=0, day=DAY):
    conn.execute(
        """INSERT INTO raw_points (data_type, start_time, end_time, value, source, raw_json,
           inserted_at, civil_date) VALUES (?,?,?,?,?, '{}', 'n', ?)""",
        (data_type, f"{day}T0{n}", f"{day}T0{n}", value, source, day))


def _daily(conn, data_type):
    return conn.execute(
        "SELECT agg_value, source, n_points FROM daily_metrics WHERE data_type=?",
        (data_type,)).fetchall()


def test_hrv_daily_value_never_mixes_sources(tmpdb, monkeypatch):
    monkeypatch.setattr(sync, "CONFIG", _config(**{"heart-rate-variability": {"sources": ["FITBIT"]}}))
    with sqlite3.connect(tmpdb) as conn:
        _raw(conn, "heart-rate-variability", 40.0, "FITBIT")
        _raw(conn, "heart-rate-variability", 80.0, "HEALTH_KIT", n=1)
        sync.rebuild_daily(conn, "heart-rate-variability")
        assert _daily(conn, "heart-rate-variability") == [(40.0, "FITBIT", 1)]


def test_rhr_falls_back_to_healthkit_when_fitbit_absent(tmpdb, monkeypatch):
    monkeypatch.setattr(sync, "CONFIG", _config(**{
        "daily-resting-heart-rate": {"sources": ["FITBIT", "HEALTH_KIT"]}}))
    t = "daily-resting-heart-rate"
    with sqlite3.connect(tmpdb) as conn:
        _raw(conn, t, 58.0, "HEALTH_KIT")
        _raw(conn, t, 50.0, "FITBIT", day="2026-10-21")
        _raw(conn, t, 70.0, "HEALTH_KIT", n=1, day="2026-10-21")
        sync.rebuild_daily(conn, t)
        rows = conn.execute(
            "SELECT date, agg_value, source FROM daily_metrics ORDER BY date").fetchall()
        assert rows == [(DAY, 58.0, "HEALTH_KIT"), ("2026-10-21", 50.0, "FITBIT")]


def test_hrv_day_with_only_unpreferred_source_has_no_row(tmpdb, monkeypatch):
    monkeypatch.setattr(sync, "CONFIG", _config(**{"heart-rate-variability": {"sources": ["FITBIT"]}}))
    with sqlite3.connect(tmpdb) as conn:
        _raw(conn, "heart-rate-variability", 80.0, "HEALTH_KIT")
        sync.rebuild_daily(conn, "heart-rate-variability")
        assert _daily(conn, "heart-rate-variability") == []


def test_types_without_preference_keep_current_behaviour(tmpdb, monkeypatch):
    monkeypatch.setattr(sync, "CONFIG", _config(**{"heart-rate": {}, "steps": {"agg": "sum"}}))
    assert sync.source_preference("heart-rate") == ()
    with sqlite3.connect(tmpdb) as conn:
        _raw(conn, "heart-rate", 60.0, "FITBIT")
        _raw(conn, "heart-rate", 80.0, "HEALTH_KIT", n=1)
        sync.rebuild_daily(conn, "heart-rate")
        assert _daily(conn, "heart-rate") == [(70.0, "", 2)]
        # server roll-up path: one bucket, source ''
        sync._upsert_rollup(conn, "steps", {"civilStartTime": {"date": {
            "year": 2026, "month": 10, "day": 20}}, "steps": {"countSum": "1234"}}, False)
        assert _daily(conn, "steps") == [(1234.0, "", 1)]


def test_v3_migration_rebuilds_mixed_days(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "CONFIG", _config(**{"heart-rate-variability": {"sources": ["FITBIT"]}}))
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.executescript(db.SCHEMA)
    for step in db.MIGRATIONS[:2]:
        step(conn)
    conn.execute("PRAGMA user_version = 2")
    _raw(conn, "heart-rate-variability", 40.0, "FITBIT")
    _raw(conn, "heart-rate-variability", 80.0, "HEALTH_KIT", n=1)
    conn.execute("INSERT INTO daily_metrics (date, data_type, agg_value, n_points) "
                 "VALUES (?, 'heart-rate-variability', 60.0, 2)", (DAY,))  # the old mixed mean
    conn.commit()
    assert db.migrate(conn) == len(db.MIGRATIONS)
    assert _daily(conn, "heart-rate-variability") == [(40.0, "FITBIT", 1)]
