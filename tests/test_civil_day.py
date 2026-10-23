"""The civil-day rule, upserted rollups and the sync lookback (C1, C2, C3).

All on throwaway databases with fake API responses; time is frozen via `civil.now`.
Owner zone: Asia/Kolkata (UTC+05:30, no DST).
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime, timedelta

import pytest
from fakes import FakeService
from health_data import civil, client, db, sync

D = date(2026, 10, 21)
NOON_IST = datetime(2026, 10, 21, 6, 30, tzinfo=UTC)  # 12:00 IST on D (the lock deadline)
SIX_IST = datetime(2026, 10, 21, 0, 30, tzinfo=UTC)  # 06:00 IST on D (first morning run)


def _ymd(d: date) -> dict:
    return {"year": d.year, "month": d.month, "day": d.day}


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(client, "list_paired_devices", lambda: {"pairedDevices": []})
    clock = {"now": NOON_IST}
    monkeypatch.setattr(civil, "now", lambda: clock["now"])

    def configure(*types: tuple[str, str]):
        monkeypatch.setattr(sync, "CONFIG", {
            "initial_backfill_days": 5,
            "data_types": {t: {"scope": "x", "agg": agg} for t, agg in types}})

    return path, clock, configure


def _q(path, sql, *args):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(sql, args).fetchall()


# --- C1: a day fetched twice keeps the later value --------------------------------------

def test_heart_rate_same_day_twice_takes_the_later_value(env, monkeypatch):
    path, clock, configure = env
    configure(("heart-rate", "mean"))
    values = iter([60.0, 75.0, 75.0])

    def window(data_type, lo, hi):
        # one bucket for D, cut at IST midnight (= D-1 18:30Z)
        yield {"startTime": "2026-10-20T18:30:00Z", "endTime": "2026-10-21T18:30:00Z",
               "heartRate": {"beatsPerMinuteAvg": next(values)}}

    monkeypatch.setattr(client, "iter_window_rollups", window)
    clock["now"] = SIX_IST
    first = sync.run()
    clock["now"] = NOON_IST
    second = sync.run()
    third = sync.run()
    assert _q(path, "SELECT date, agg_value FROM daily_metrics WHERE data_type='heart-rate'") == [
        (D.isoformat(), 75.0)]
    assert _q(path, "SELECT start_time, value, civil_date FROM raw_points WHERE data_type='heart-rate'") == [
        (D.isoformat(), 75.0, D.isoformat())]
    # inserted counts mean new-or-changed rows
    assert [r["heart-rate"]["inserted"] for r in (first, second, third)] == [1, 1, 0]


def test_daily_rollup_raw_receipt_is_not_stale(env, monkeypatch):
    path, _, configure = env
    configure(("steps", "sum"))
    values = iter(["1000", "8000"])

    def rollups(data_type, lo, hi):
        yield {"civilStartTime": {"date": _ymd(D)}, "steps": {"countSum": next(values)}}

    monkeypatch.setattr(client, "iter_daily_rollups", rollups)
    sync.run()
    sync.run()
    assert _q(path, "SELECT value FROM raw_points WHERE data_type='steps'") == [(8000.0,)]
    assert _q(path, "SELECT agg_value FROM daily_metrics WHERE data_type='steps'") == [(8000.0,)]


# --- C2: the lookback picks up late uploads ---------------------------------------------

def test_late_arriving_sample_is_picked_up_by_the_lookback(env, monkeypatch):
    path, clock, configure = env
    configure(("heart-rate-variability", "mean"))
    uploaded: list[dict] = []
    windows: list[tuple[str, str]] = []

    def points(data_type, start, end):
        windows.append((start, end))
        lo, hi = datetime.fromisoformat(start), datetime.fromisoformat(end)
        for p in uploaded:
            t = datetime.fromisoformat(p["heartRateVariability"]["sampleTime"]["physicalTime"].replace("Z", "+00:00"))
            if lo <= t < hi:
                yield p

    def hrv(ts: str, ms: int) -> dict:
        return {"heartRateVariability": {"sampleTime": {"physicalTime": ts},
                                         "rootMeanSquareOfSuccessiveDifferencesMilliseconds": ms}}

    monkeypatch.setattr(client, "iter_data_points", points)
    clock["now"] = SIX_IST
    sync.run()  # cursor now at 06:00 IST on D
    # The watch uploads a night sample from D-2 (02:00 IST) only now.
    uploaded.append(hrv("2026-10-18T20:30:00Z", 40))
    clock["now"] = NOON_IST
    result = sync.run()
    assert result["heart-rate-variability"]["inserted"] == 1
    assert _q(path, "SELECT date FROM daily_metrics WHERE data_type='heart-rate-variability'") == [
        ("2026-10-19",)]
    # window = D-3 IST midnight .. D+1 IST midnight
    assert windows[-1] == ("2026-10-18T00:00:00+05:30", "2026-10-22T00:00:00+05:30")
    assert sync.run()["heart-rate-variability"]["inserted"] == 0  # idempotent


def test_missed_runs_widen_the_window_back_to_the_cursor():
    lo, hi = civil.sync_days("2026-10-10T03:00:00+00:00", 30)
    assert lo == date(2026, 10, 10) and hi == civil.today() + timedelta(days=1)


def test_window_is_lookback_plus_today(monkeypatch):
    monkeypatch.setattr(civil, "now", lambda: NOON_IST)
    assert civil.sync_days(SIX_IST.isoformat(), 30) == (D - timedelta(days=civil.LOOKBACK_DAYS),
                                                        D + timedelta(days=1))
    assert civil.sync_days(None, 30) == (D - timedelta(days=30), D + timedelta(days=1))


# --- C3: windows and attribution in the owner zone --------------------------------------

def test_requests_at_noon_ist_see_last_nights_data_and_today(env, monkeypatch):
    path, clock, configure = env
    configure(("sleep", "sum"), ("daily-resting-heart-rate", "mean"),
              ("heart-rate-variability", "mean"), ("heart-rate", "mean"), ("steps", "sum"))
    fake = FakeService({
        "list": [{"dataPoints": []}], "rollUp": [{"rollupDataPoints": []}],
        "dailyRollUp": [{"rollupDataPoints": []}],
    })
    monkeypatch.setattr(client, "service", lambda: fake)
    clock["now"] = SIX_IST
    sync.run()  # the 06:00 IST run sets the cursors
    fake.points.calls.clear()
    clock["now"] = NOON_IST
    sync.run()
    filters = [kw["filter"] for m, kw in fake.points.calls if m == "list"]
    bodies = {m: kw["body"] for m, kw in fake.points.calls if m != "list"}
    # sleep: civil end time, owner-zone wall clock, today included
    assert ('sleep.interval.civil_end_time >= "2026-10-18T00:00:00" AND '
            'sleep.interval.civil_end_time < "2026-10-22T00:00:00"') in filters
    # daily types: owner-zone dates, today included (the old code produced date >= D AND date < D)
    assert ('daily_resting_heart_rate.date >= "2026-10-18" AND '
            'daily_resting_heart_rate.date < "2026-10-22"') in filters
    # samples: the UTC instants of owner-zone midnights
    assert ('heart_rate_variability.sample_time.physical_time >= "2026-10-17T18:30:00+00:00" AND '
            'heart_rate_variability.sample_time.physical_time < "2026-10-21T18:30:00+00:00"') in filters
    # heart-rate rollUp windows start at owner-zone midnight
    assert bodies["rollUp"]["range"] == {"startTime": "2026-10-17T18:30:00Z", "endTime": "2026-10-21T18:30:00Z"}
    assert bodies["dailyRollUp"]["range"]["end"] == {"date": _ymd(D + timedelta(days=1))}


def test_today_is_the_owner_zone_date(monkeypatch):
    monkeypatch.setattr(civil, "now", lambda: datetime(2026, 10, 20, 19, 0, tzinfo=UTC))  # 00:30 IST
    assert civil.today() == D


@pytest.mark.parametrize(("ts", "civil_ts"), [
    ("2026-10-21T06:30:00+00:00", "2026-10-21T12:00:00"),  # converted, not stripped
    ("2026-10-21T06:30:00.456Z", "2026-10-21T12:00:00"),
    ("2026-10-21T12:00:00+05:30", "2026-10-21T12:00:00"),
    ("2026-10-21T12:00:00", "2026-10-21T12:00:00"),  # zone-less is already civil
])
def test_civil_filter_bounds_convert_to_the_owner_zone(ts, civil_ts):
    assert client._as_civil(ts) == civil_ts


def test_daily_filter_bound_is_the_owner_zone_date():
    # 20:00Z on the 20th is 01:30 IST on the 21st
    assert client._as_date("2026-10-20T20:00:00+00:00") == "2026-10-21"


@pytest.mark.parametrize(("data_type", "point", "day"), [
    # sleep 23:00 IST D-1 -> 06:30 IST D belongs to D (the day it ends)
    ("sleep", {"sleep": {"interval": {"startTime": "2026-10-20T17:30:00Z",
                                      "endTime": "2026-10-21T01:00:00Z"}}}, "2026-10-21"),
    # a sample at 01:30 IST belongs to that IST day, not the UTC date
    ("heart-rate-variability", {"heartRateVariability": {
        "sampleTime": {"physicalTime": "2026-10-20T20:00:00Z"}}}, "2026-10-21"),
    # exercise belongs to the IST day it starts (00:30 IST)
    ("exercise", {"exercise": {"interval": {"startTime": "2026-10-20T19:00:00Z",
                                            "endTime": "2026-10-20T20:00:00Z"}}}, "2026-10-21"),
    # zone-less physical times are UTC
    ("exercise", {"exercise": {"interval": {"startTime": "2026-10-20T19:00:00.5",
                                            "endTime": "2026-10-20T20:00:00"}}}, "2026-10-21"),
    # daily summaries keep the API's date
    ("daily-resting-heart-rate", {"dailyRestingHeartRate": {"date": _ymd(D)}}, "2026-10-21"),
])
def test_day_of_point(data_type, point, day):
    assert civil.day_of_point(data_type, point) == day


def test_window_bucket_day_is_owner_zone():
    assert civil.day_of_window_bucket({"startTime": "2026-10-20T18:30:00Z"}) == "2026-10-21"
    assert civil.day_of_window_bucket({"civilStartTime": {"date": _ymd(D)}}) == "2026-10-21"


def test_sync_stores_sleep_on_the_morning_it_ends(env, monkeypatch):
    path, _, configure = env
    configure(("sleep", "sum"), ("heart-rate-variability", "mean"))

    def points(data_type, start, end):
        if data_type == "sleep":
            yield {"sleep": {"interval": {"startTime": "2026-10-20T17:30:00Z",
                                          "endTime": "2026-10-21T01:00:00Z"}}}
        else:
            yield {"heartRateVariability": {"sampleTime": {"physicalTime": "2026-10-20T20:00:00Z"},
                                            "rootMeanSquareOfSuccessiveDifferencesMilliseconds": 40}}

    monkeypatch.setattr(client, "iter_data_points", points)
    sync.run()
    assert _q(path, "SELECT data_type, date, n_points FROM daily_metrics ORDER BY data_type") == [
        ("heart-rate-variability", "2026-10-21", 1), ("sleep", "2026-10-21", 1)]


def test_rebuild_drops_days_without_support(env, monkeypatch):
    path, _, configure = env
    configure(("weight", "mean"))
    monkeypatch.setattr(client, "iter_data_points", lambda *a: iter([]))
    db.init_db()
    with db.connect() as conn:
        conn.execute("INSERT INTO daily_metrics (date, data_type, agg_value, n_points) VALUES ('2026-10-19', 'weight', 70, 1)")  # stale UTC-day row
    sync.run()
    assert _q(path, "SELECT COUNT(*) FROM daily_metrics WHERE data_type='weight'") == [(0,)]


def test_device_failure_is_not_a_failed_run():
    assert sync.exit_code({"steps": {"fetched": 1, "inserted": 0}, "_devices": {"error": "403"}}) == 0
    assert sync.failed_types({"steps": {"error": "x"}, "_devices": {"error": "403"}}) == ["steps"]


def test_device_rename_does_not_duplicate_points(env, monkeypatch):
    """Upstream renamed the device ("Google Fitbit Air" -> "Fitbit Air"); the key is the platform."""
    path, clock, configure = env
    configure(("sleep", "sum"))
    names = iter(["Google Fitbit Air", "Fitbit Air", "Fitbit Air"])

    def points(data_type, start, end):
        yield {"dataSource": {"platform": "FITBIT", "device": {"displayName": next(names)}},
               "sleep": {"interval": {"startTime": "2026-10-20T17:30:00Z",
                                      "endTime": "2026-10-21T01:00:00Z"}}}

    monkeypatch.setattr(client, "iter_data_points", points)
    sync.run()
    assert sync.run()["sleep"]["inserted"] == 1  # same row, raw_json updated (new name)
    assert sync.run()["sleep"]["inserted"] == 0
    assert _q(path, "SELECT source, COUNT(*) FROM raw_points GROUP BY source") == [("FITBIT", 1)]
    assert _q(path, "SELECT agg_value, n_points FROM daily_metrics") == [(450.0, 1)]  # not doubled
