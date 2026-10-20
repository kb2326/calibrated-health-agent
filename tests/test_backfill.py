"""Backfill: window caps, resumability, idempotency, and the cha-data CLI."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, timedelta

import pytest
from health_data import backfill as bf
from health_data import client, db, sync
from health_data.cli import app
from typer.testing import CliRunner

TODAY = date(2026, 10, 20)
SINCE = date(2026, 5, 1)  # 172 days before TODAY


def _civil(d: date) -> dict:
    return {"date": {"year": d.year, "month": d.month, "day": d.day}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(bf, "_today", lambda: TODAY)
    monkeypatch.setattr(sync, "CONFIG", {
        "initial_backfill_days": 5,
        "data_types": {
            "steps": {"scope": "x", "agg": "sum"},
            "heart-rate": {"scope": "x", "agg": "mean"},
            "weight": {"scope": "x", "agg": "mean"},
        },
    })
    calls: dict[str, list[tuple[date, date]]] = {}
    state: dict = {"fail_on": None}  # (type, call_number) to raise a 429 on

    def _record(data_type, lo, hi):
        calls.setdefault(data_type, []).append((lo, hi))
        if state["fail_on"] == (data_type, len(calls[data_type])):
            raise client.HealthApiError("429: quota")
        state["mid"] = state.get("mid_on") == (data_type, len(calls[data_type]))

    def fake_daily(data_type, lo, hi):
        _record(data_type, lo, hi)
        for i in range((hi - lo).days):
            d = lo + timedelta(days=i)
            yield {"civilStartTime": _civil(d), "steps": {"countSum": "1000"}}

    def fake_window(data_type, lo, hi):
        _record(data_type, lo, hi)
        for i in range((hi - lo).days):
            d = lo + timedelta(days=i)
            yield {"startTime": f"{d.isoformat()}T00:00:00Z",
                   "heartRate": {"beatsPerMinuteAvg": 60.0}}
            if state["mid"] and i == 3:  # fail partway through the window
                raise client.HealthApiError("429: quota")

    def fake_points(data_type, start, end):
        _record(data_type, date.fromisoformat(start[:10]), date.fromisoformat(end[:10]))
        lo, hi = calls[data_type][-1]
        for i in range((hi - lo).days):
            d = lo + timedelta(days=i)
            yield {"weight": {"sampleTime": {"physicalTime": f"{d.isoformat()}T06:00:00Z"},
                              "weightGrams": 70000}}

    monkeypatch.setattr(client, "iter_daily_rollups", fake_daily)
    monkeypatch.setattr(client, "iter_window_rollups", fake_window)
    monkeypatch.setattr(client, "iter_data_points", fake_points)
    monkeypatch.setattr(client, "list_paired_devices", lambda: {"pairedDevices": []})
    return calls, state, tmp_path / "t.db"


def _rows(path, data_type):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT start_time) FROM raw_points WHERE data_type=?",
            (data_type,)).fetchone()


def test_backfill_splits_windows_per_type_cap(env):
    calls, _, _ = env
    bf.backfill(SINCE, ["steps", "heart-rate", "weight"])
    for lo, hi in calls["heart-rate"]:
        assert (hi - lo).days <= 14
    for lo, hi in calls["steps"] + calls["weight"]:
        assert (hi - lo).days <= 90
    assert len(calls["heart-rate"]) == 13  # ceil(172 / 14)
    assert len(calls["steps"]) == 2        # ceil(172 / 90)
    assert calls["steps"][0][0] == SINCE and calls["steps"][-1][1] == TODAY


def test_backfill_resumes_after_failure(env):
    calls, state, path = env
    clean = bf.backfill(SINCE, ["heart-rate"])
    clean_rows = _rows(path, "heart-rate")
    path.unlink()
    for ext in ("-wal", "-shm"):
        path.with_name(path.name + ext).unlink(missing_ok=True)
    calls.clear()

    state["fail_on"] = ("heart-rate", 3)
    with pytest.raises(bf.BackfillError) as err:
        bf.backfill(SINCE, ["heart-rate"])
    assert err.value.inserted["heart-rate"] == 28  # windows 1 and 2 kept
    with closing(sqlite3.connect(path)) as conn:
        cursor = conn.execute(
            "SELECT cursor_time FROM sync_state WHERE data_type='backfill:heart-rate'"
        ).fetchone()[0]
    assert cursor == f"{SINCE}..{SINCE + timedelta(days=28)}"

    state["fail_on"] = None
    calls.clear()
    resumed = bf.backfill(SINCE, ["heart-rate"])
    assert calls["heart-rate"][0][0] == SINCE + timedelta(days=28)
    assert len(calls["heart-rate"]) == 11
    assert 28 + resumed["heart-rate"] == clean["heart-rate"]
    total, distinct = _rows(path, "heart-rate")
    assert (total, distinct) == clean_rows and total == distinct


def test_backfill_is_idempotent(env):
    calls, _, _ = env
    first = bf.backfill(SINCE)
    assert all(n > 0 for n in first.values())
    calls.clear()
    assert bf.backfill(SINCE) == dict.fromkeys(first, 0)
    assert calls == {}  # nothing refetched


def test_backfill_earlier_since_starts_over_without_duplicates(env):
    _, _, path = env
    bf.backfill(SINCE, ["steps"])
    again = bf.backfill(SINCE - timedelta(days=10), ["steps"])
    assert again["steps"] == 10
    total, distinct = _rows(path, "steps")
    assert total == distinct == (TODAY - SINCE).days + 10


def test_cli_backfill_reports_counts_and_exit_codes(env):
    _, state, _ = env
    runner = CliRunner()
    ok = runner.invoke(app, ["backfill", "--since", "2026-10-01", "--type", "steps"])
    assert ok.exit_code == 0 and "inserted=" in ok.output and "total inserted: 19" in ok.output
    state["fail_on"] = ("heart-rate", 1)
    bad = runner.invoke(app, ["backfill", "--since", "2026-10-01", "--type", "heart-rate"])
    assert bad.exit_code == 1 and "FAILED" in bad.output


def test_cli_wires_expected_commands_only():
    runner = CliRunner()
    top = runner.invoke(app, ["--help"]).output
    for name in ("sync", "backfill", "probe", "parity", "db", "auth", "journal"):
        assert name in top
    assert "push-secret" not in runner.invoke(app, ["auth", "--help"]).output
    dbhelp = runner.invoke(app, ["db", "--help"]).output
    assert "vacuum" in dbhelp and "migrate" in dbhelp
    assert "pull" not in dbhelp and "push" not in dbhelp


def test_cli_db_migrate_and_vacuum(env):
    runner = CliRunner()
    assert "schema version" in runner.invoke(app, ["db", "migrate"]).output
    out = runner.invoke(app, ["db", "vacuum"])
    assert out.exit_code == 0 and "MB" in out.output


def test_auth_error_names_cha_data_login(monkeypatch, tmp_path):
    from health_data import auth

    monkeypatch.setattr(auth, "TOKEN_PATH", tmp_path / "none.json")
    monkeypatch.setattr(auth, "LEGACY_CREDENTIALS_PATH", tmp_path / "none2.json")
    with pytest.raises(auth.AuthError, match="cha-data auth login"):
        auth.get_credentials()
    res = CliRunner().invoke(app, ["auth", "status"])
    assert res.exit_code == 1 and "cha-data auth login" in res.output


def test_failed_window_rolls_back_partial_rows_and_keeps_cursor(env):
    calls, state, path = env
    state["mid_on"] = ("heart-rate", 3)
    with pytest.raises(bf.BackfillError) as err:
        bf.backfill(SINCE, ["heart-rate"])
    assert err.value.inserted["heart-rate"] == 28
    total, distinct = _rows(path, "heart-rate")
    assert total == distinct == 28  # nothing from the failed window persisted
    with closing(sqlite3.connect(path)) as conn:
        cursor = conn.execute(
            "SELECT cursor_time FROM sync_state WHERE data_type='backfill:heart-rate'"
        ).fetchone()[0]
    assert cursor == f"{SINCE}..{SINCE + timedelta(days=28)}"


def test_coverage_never_shrinks_on_a_later_since(env):
    calls, _, path = env
    march, june = date(2026, 3, 1), date(2026, 6, 1)
    first = bf.backfill(march, ["steps", "heart-rate"])
    assert all(n > 0 for n in first.values())
    calls.clear()
    assert bf.backfill(june, ["steps", "heart-rate"]) == {"steps": 0, "heart-rate": 0}
    assert calls == {}  # June is inside covered history
    with closing(sqlite3.connect(path)) as conn:
        cursor = conn.execute(
            "SELECT cursor_time FROM sync_state WHERE data_type='backfill:steps'"
        ).fetchone()[0]
    assert cursor == f"{march}..{TODAY}"
    assert bf.backfill(march, ["steps", "heart-rate"]) == {"steps": 0, "heart-rate": 0}
    assert calls == {}  # no refetch of already-covered windows


def test_earlier_since_fetches_only_the_missing_prefix(env):
    calls, _, _ = env
    bf.backfill(SINCE, ["steps"])
    calls.clear()
    bf.backfill(SINCE - timedelta(days=100), ["steps"])
    assert all(hi <= SINCE for _, hi in calls["steps"])
    assert sum((hi - lo).days for lo, hi in calls["steps"]) == 100


def test_gap_since_keeps_covered_history_contiguous(env):
    calls, state, path = env
    march, june = date(2026, 3, 1), date(2026, 6, 1)
    state["fail_on"] = ("steps", 2)  # window 1 (90 days) lands, window 2 fails
    with pytest.raises(bf.BackfillError):
        bf.backfill(march, ["steps"])
    with closing(sqlite3.connect(path)) as conn:
        stored = conn.execute(
            "SELECT cursor_time FROM sync_state WHERE data_type='backfill:steps'"
        ).fetchone()[0]
    assert stored == f"{march}..{march + timedelta(days=90)}"  # ends before June
    state["fail_on"] = None
    bf.backfill(june, ["steps"])  # gap: fills stored end .. today, keeps lo
    calls.clear()
    assert bf.backfill(march, ["steps"]) == {"steps": 0}
    assert calls == {}
    with closing(sqlite3.connect(path)) as conn:
        cursor = conn.execute(
            "SELECT cursor_time FROM sync_state WHERE data_type='backfill:steps'"
        ).fetchone()[0]
    assert cursor == f"{march}..{TODAY}"
    total, distinct = _rows(path, "steps")
    assert total == distinct == (TODAY - march).days
