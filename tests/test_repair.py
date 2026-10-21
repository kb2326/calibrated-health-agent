"""`cha-data db repair`: re-fetch and recompute under the civil-day rule (fakes only)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest
from health_data import civil, cli, client, db, repair, store, sync
from typer.testing import CliRunner

NOW = datetime(2026, 10, 21, 6, 30, tzinfo=UTC)  # 12:00 IST


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(civil, "now", lambda: NOW)
    monkeypatch.setattr(sync, "CONFIG", {"initial_backfill_days": 5, "data_types": {
        "heart-rate": {"scope": "x", "agg": "mean"},
        "heart-rate-variability": {"scope": "x", "agg": "mean"}}})

    def window(data_type, lo, hi):
        d = lo
        while d < hi:
            start = civil.midnight(d).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            yield {"startTime": start, "heartRate": {"beatsPerMinuteAvg": 70.0}}
            d += timedelta(days=1)

    hrv = {"heartRateVariability": {"sampleTime": {"physicalTime": "2026-10-19T20:00:00Z"},
                                    "rootMeanSquareOfSuccessiveDifferencesMilliseconds": 40}}
    late = {"heartRateVariability": {"sampleTime": {"physicalTime": "2026-10-18T21:00:00Z"},
                                     "rootMeanSquareOfSuccessiveDifferencesMilliseconds": 50}}
    monkeypatch.setattr(client, "iter_window_rollups", window)
    monkeypatch.setattr(client, "iter_data_points", lambda *a: iter([hrv, late]))
    db.init_db()
    with db.connect() as conn:
        # Pre-fix state: heart-rate cut at UTC days (one frozen), HRV attributed to the UTC date.
        for day, v in (("2026-10-17", 60.0), ("2026-10-18", 61.0)):
            conn.execute("INSERT INTO raw_points (data_type, start_time, end_time, value, source,"
                         " raw_json, inserted_at, civil_date) VALUES ('heart-rate', ?, ?, ?,"
                         " 'dailyRollUp', '{}', 'n', ?)", (day, day, v, day))
            conn.execute("INSERT INTO daily_metrics VALUES (?, 'heart-rate', ?, 1)", (day, v))
        conn.execute("INSERT INTO raw_points (data_type, start_time, end_time, value, source, raw_json,"
                     " inserted_at, civil_date) VALUES ('heart-rate-variability', '2026-10-19T20:00:00Z',"
                     " '2026-10-19T20:00:00Z', 40, 'unknown', ?, 'n', '2026-10-19')", (json.dumps(hrv),))
        conn.execute("INSERT INTO daily_metrics VALUES ('2026-10-19', 'heart-rate-variability', 40, 1)")
    return path


def _q(path, sql):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(sql).fetchall()


def test_repair_recuts_rollups_and_reattributes_points(env):
    report = repair.repair()
    hr = report["heart-rate"]
    assert hr["before"]["days"] == 2 and hr["window"] == "2026-10-17..2026-10-22"
    assert _q(env, "SELECT date, agg_value FROM daily_metrics WHERE data_type='heart-rate' ORDER BY date") == [
        (f"2026-10-{d}", 70.0) for d in range(17, 22)]
    # HRV: 20:00Z on the 19th is the 20th in IST; the late point (21:00Z on the 18th) is recovered
    assert _q(env, "SELECT date, n_points FROM daily_metrics WHERE data_type='heart-rate-variability'"
                   " ORDER BY date") == [("2026-10-19", 1), ("2026-10-20", 1)]
    assert report["heart-rate-variability"]["after"]["raw_rows"] == 2
    assert repair.repair()["heart-rate"]["after"] == report["heart-rate"]["after"]  # rerun is stable


def test_repair_failure_rolls_back_that_type_only(env, monkeypatch):
    def boom(*a):
        raise client.HealthApiError("429: quota")

    monkeypatch.setattr(client, "iter_window_rollups", boom)
    report = repair.repair()
    assert "error" in report["heart-rate"] and "error" not in report["heart-rate-variability"]
    assert _q(env, "SELECT COUNT(*) FROM daily_metrics WHERE data_type='heart-rate'") == [(2,)]


def test_repair_days_limits_the_window(env):
    assert repair.repair(days=2)["heart-rate"]["window"] == "2026-10-19..2026-10-22"


def test_cli_repair_on_a_copy_never_pushes(env, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "push_recorded", lambda *a, **k: pytest.fail("must not push"))
    monkeypatch.setattr(store, "require_fresh", lambda *a, **k: pytest.fail("must not touch GCS"))
    copy = tmp_path / "copy.db"
    copy.write_bytes(env.read_bytes())
    original = db.DB_PATH
    result = CliRunner().invoke(cli.app, ["db", "repair", "--db", str(copy)])
    assert result.exit_code == 0, result.output
    assert "heart-rate" in result.output and "70" not in result.output  # counts and days only
    assert db.DB_PATH == original
    assert _q(copy, "SELECT COUNT(*) FROM daily_metrics WHERE data_type='heart-rate'") == [(5,)]
