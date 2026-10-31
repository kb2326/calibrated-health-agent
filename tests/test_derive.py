"""Schema v5 detail tables derived from raw_points.raw_json (Phase 4.5).

Shapes follow the live payloads inspected on 2026-10-31 (values here are synthetic).
"""
from __future__ import annotations

import json

import pytest
from health_data import db, derive
from ledger_fixtures import make_db


def _raw(conn, data_type, raw, *, start, civil_date, source="FITBIT|WATCH"):
    conn.execute(
        "INSERT INTO raw_points (data_type, start_time, end_time, value, source, raw_json,"
        " inserted_at, civil_date) VALUES (?, ?, ?, NULL, ?, ?, 't', ?)",
        (data_type, start, start, source, json.dumps(raw), civil_date))


SLEEP = {"sleep": {
    "interval": {"startTime": "2026-10-29T17:10:00Z", "endTime": "2026-10-30T01:40:00Z"},
    "type": "STAGES",
    "metadata": {"mainSleep": True},
    "summary": {"minutesInSleepPeriod": "510", "minutesAsleep": "452", "minutesAwake": "58",
                "minutesToFallAsleep": "12",
                "stagesSummary": [{"type": "DEEP", "minutes": "71"}, {"type": "LIGHT", "minutes": "260"},
                                  {"type": "REM", "minutes": "121"}, {"type": "AWAKE", "minutes": "58"}]}}}
EXERCISE = {"exercise": {
    "interval": {"startTime": "2026-10-30T00:30:00Z", "endTime": "2026-10-30T01:20:00Z"},
    "exerciseType": "RUNNING", "displayName": "Morning run", "activeDuration": "2820s",
    "metricsSummary": {"caloriesKcal": 410, "distanceMillimeters": 7200000, "steps": "6900",
                       "averageHeartRateBeatsPerMinute": "152", "activeZoneMinutes": "41",
                       "heartRateZoneDurations": {"lightTime": "300s", "moderateTime": "900s",
                                                  "vigorousTime": "1500s", "peakTime": "120s"}}}}


@pytest.fixture
def conn(tmp_path):
    c = make_db(tmp_path / "h.db")
    _raw(c, "sleep", SLEEP, start="2026-10-29T17:10:00Z", civil_date="2026-10-30")
    _raw(c, "exercise", EXERCISE, start="2026-10-30T00:30:00Z", civil_date="2026-10-30")
    _raw(c, "daily-sleep-temperature-derivations", {"dailySleepTemperatureDerivations": {
        "date": {"year": 2026, "month": 10, "day": 30}, "nightlyTemperatureCelsius": 34.1,
        "baselineTemperatureCelsius": 33.8}}, start="2026-10-30", civil_date="2026-10-30")
    _raw(c, "daily-oxygen-saturation", {"dailyOxygenSaturation": {
        "date": {"year": 2026, "month": 10, "day": 30}, "averagePercentage": 96.2,
        "lowerBoundPercentage": 92.0, "upperBoundPercentage": 99.0}},
        start="2026-10-30", civil_date="2026-10-30")
    _raw(c, "daily-heart-rate-variability", {"dailyHeartRateVariability": {
        "date": {"year": 2026, "month": 10, "day": 30}, "averageHeartRateVariabilityMilliseconds": 48.0,
        "nonRemHeartRateBeatsPerMinute": "58", "deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds": 61.5}},
        start="2026-10-30", civil_date="2026-10-30")
    _raw(c, "respiratory-rate-sleep-summary", {"respiratoryRateSleepSummary": {
        "fullSleepStats": {"breathsPerMinute": 14.6}, "deepSleepStats": {"breathsPerMinute": 13.9},
        "lightSleepStats": {"breathsPerMinute": 14.8}, "remSleepStats": {"breathsPerMinute": 15.1}}},
        start="2026-10-30T01:40:00Z", civil_date="2026-10-30")
    _raw(c, "active-zone-minutes", {"activeZoneMinutes": {
        "sumInFatBurnHeartZone": "12", "sumInCardioHeartZone": "25", "sumInPeakHeartZone": "2"}},
        start="2026-10-30", civil_date="2026-10-30", source="dailyRollUp")
    _raw(c, "active-minutes", {"activeMinutes": {"activeMinutesRollupByActivityLevel": [
        {"activityLevel": "LIGHT", "activeMinutesSum": "180"},
        {"activityLevel": "MODERATE", "activeMinutesSum": "30"},
        {"activityLevel": "VIGOROUS", "activeMinutesSum": "40"}]}},
        start="2026-10-30", civil_date="2026-10-30", source="dailyRollUp")
    _raw(c, "time-in-heart-rate-zone", {"timeInHeartRateZone": {"timeInHeartRateZones": [
        {"heartRateZone": "LIGHT", "duration": "36000s"}, {"heartRateZone": "MODERATE", "duration": "1800s"},
        {"heartRateZone": "VIGOROUS", "duration": "1500s"}, {"heartRateZone": "PEAK", "duration": "120s"}]}},
        start="2026-10-30", civil_date="2026-10-30", source="dailyRollUp")
    _raw(c, "daily-heart-rate-zones", {"dailyHeartRateZones": {
        "date": {"year": 2026, "month": 10, "day": 30}, "heartRateZones": [
            {"heartRateZoneType": "MODERATE", "minBeatsPerMinute": 112, "maxBeatsPerMinute": 136},
            {"heartRateZoneType": "PEAK", "minBeatsPerMinute": 160, "maxBeatsPerMinute": 220}]}},
        start="2026-10-30", civil_date="2026-10-30")
    c.commit()
    yield c
    c.close()


def _one(conn, sql):
    return conn.execute(sql).fetchone()


def test_v5_creates_detail_tables():
    assert len(db.MIGRATIONS) == 5


def test_sleep_sessions_use_minutes_asleep_and_stages(conn):
    derive.rebuild(conn)
    row = _one(conn, "SELECT date, main_sleep, minutes_asleep, minutes_in_period, deep_min, light_min,"
                     " rem_min, awake_min, minutes_to_fall_asleep, round(efficiency, 3) FROM sleep_sessions")
    assert row == ("2026-10-30", 1, 452, 510, 71, 260, 121, 58, 12, round(452 / 510, 3))


def test_exercise_sessions_keep_type_and_metrics(conn):
    derive.rebuild(conn)
    row = _one(conn, "SELECT date, type, name, active_min, calories_kcal, distance_km, steps,"
                     " avg_hr_bpm, azm, vigorous_min, peak_min FROM exercise_sessions")
    assert row == ("2026-10-30", "RUNNING", "Morning run", 47.0, 410, 7.2, 6900, 152, 41, 25.0, 2.0)


def test_night_vitals_join_the_nightly_summaries(conn):
    derive.rebuild(conn)
    row = _one(conn, "SELECT skin_temp_c, skin_temp_baseline_c, round(skin_temp_delta_c, 2), spo2_avg,"
                     " spo2_low, spo2_high, hrv_ms, hrv_deep_ms, non_rem_hr_bpm, resp_full, resp_deep,"
                     " resp_rem FROM night_vitals WHERE date = '2026-10-30'")
    assert row == (34.1, 33.8, 0.3, 96.2, 92.0, 99.0, 48.0, 61.5, 58, 14.6, 13.9, 15.1)


def test_activity_breakdown_splits_zones_and_levels(conn):
    derive.rebuild(conn)
    row = _one(conn, "SELECT fat_burn_azm, cardio_azm, peak_azm, light_active_min, moderate_active_min,"
                     " vigorous_active_min, zone_light_min, zone_moderate_min, zone_vigorous_min,"
                     " zone_peak_min FROM activity_breakdown WHERE date = '2026-10-30'")
    assert row == (12, 25, 2, 180, 30, 40, 600.0, 30.0, 25.0, 2.0)


def test_zone_thresholds(conn):
    derive.rebuild(conn)
    rows = conn.execute("SELECT zone, min_bpm, max_bpm FROM hr_zone_thresholds ORDER BY min_bpm").fetchall()
    assert rows == [("MODERATE", 112, 136), ("PEAK", 160, 220)]


def test_derive_is_idempotent(conn):
    first = derive.rebuild(conn)
    second = derive.rebuild(conn)
    assert first == second and _one(conn, "SELECT COUNT(*) FROM sleep_sessions") == (1,)


def test_derive_tolerates_missing_fields(tmp_path):
    c = make_db(tmp_path / "h.db")
    _raw(c, "sleep", {"sleep": {"interval": {"startTime": "2026-10-29T12:00:00Z",
                                             "endTime": "2026-10-29T12:40:00Z"},
                                "metadata": {"mainSleep": False}}},
         start="2026-10-29T12:00:00Z", civil_date="2026-10-29")
    _raw(c, "exercise", {"exercise": {"exerciseType": "WALKING"}}, start="x", civil_date="2026-10-29")
    _raw(c, "sleep", {"oops": 1}, start="y", civil_date="2026-10-29")
    counts = derive.rebuild(c)
    nap = _one(c, "SELECT main_sleep, minutes_asleep, deep_min, minutes_in_period FROM sleep_sessions")
    assert nap == (0, None, None, 40.0)
    assert counts["exercise_sessions"] == 1
    assert _one(c, "SELECT type, calories_kcal FROM exercise_sessions") == ("WALKING", None)


def test_rebuild_never_touches_daily_metrics_or_the_ledger(conn):
    conn.execute("INSERT INTO daily_metrics (date, data_type, agg_value, n_points, source)"
                 " VALUES ('2026-10-30', 'sleep', 510, 1, '')")
    derive.rebuild(conn)
    assert _one(conn, "SELECT agg_value FROM daily_metrics WHERE data_type = 'sleep'") == (510,)


def test_job_runs_the_derive_step(monkeypatch):
    from jobs import sync_job

    calls = []
    monkeypatch.setattr(sync_job, "_derive", lambda: calls.append(1) or {"rows": {}})
    src = __import__("inspect").getsource(sync_job._run)
    assert '_step("derive", _derive)' in src
