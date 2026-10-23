"""Sync behaviour per data-type family, extract handlers for the extra types,
devices, scopes, and the 50 MB budget - all on throwaway DBs with fixtures."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml
from health_data import auth, client, db, reconcile, sync

REPO = Path(__file__).resolve().parents[1]


def _civil(d: date) -> dict:
    return {"date": {"year": d.year, "month": d.month, "day": d.day}}


def _ymd(d: date) -> dict:
    return {"year": d.year, "month": d.month, "day": d.day}


@pytest.fixture
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(client, "list_paired_devices", lambda: {"pairedDevices": []})
    return tmp_path / "t.db"


def _config(*types: tuple[str, str]) -> dict:
    return {"initial_backfill_days": 5,
            "data_types": {t: {"scope": "x", "agg": agg} for t, agg in types}}


def _no_list(*a, **k):
    raise AssertionError("steps must come from dailyRollUp, never per-point list")


def test_summed_types_store_daily_rollup_not_points(tmpdb, monkeypatch):
    days = [date(2026, 10, 1) + timedelta(days=i) for i in range(5)]
    buckets = [{"civilStartTime": _civil(d), "steps": {"countSum": str(1000 + i)}}
               for i, d in enumerate(days)]
    monkeypatch.setattr(sync, "CONFIG", _config(("steps", "sum")))
    monkeypatch.setattr(client, "iter_daily_rollups", lambda *a, **k: iter(buckets))
    monkeypatch.setattr(client, "iter_data_points", _no_list)
    result = sync.run()
    assert "error" not in result["steps"]
    with sqlite3.connect(tmpdb) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM daily_metrics WHERE data_type='steps'").fetchone()[0] == 5
        assert conn.execute(
            "SELECT COUNT(*) FROM raw_points WHERE data_type='steps'").fetchone()[0] == 5
        assert conn.execute(
            "SELECT COUNT(DISTINCT source) FROM raw_points WHERE data_type='steps'"
        ).fetchone()[0] == 1


def test_unknown_type_records_error_and_continues(tmpdb, monkeypatch):
    def fake_points(data_type, start, end):
        if data_type == "weight":
            raise client.HealthApiError("400: not a thing")
        yield {"dailyRestingHeartRate": {"date": _ymd(date(2026, 10, 2)),
                                         "beatsPerMinute": "60"}}

    monkeypatch.setattr(sync, "CONFIG", _config(
        ("weight", "mean"), ("daily-resting-heart-rate", "mean")))
    monkeypatch.setattr(client, "iter_data_points", fake_points)
    result = sync.run()
    assert "error" in result["weight"]
    assert result["daily-resting-heart-rate"]["inserted"] == 1
    assert sync.exit_code(result) == 1
    with sqlite3.connect(tmpdb) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sync_state").fetchone()[0] == 1


def test_unexpected_error_reports_only_committed_types(tmpdb, monkeypatch):
    def fake_points(data_type, start, end):
        if data_type == "weight":
            raise ConnectionError("network down")  # not a HealthApiError: stops the run
        yield {"dailyRestingHeartRate": {"date": _ymd(date(2026, 10, 2)),
                                         "beatsPerMinute": "60"}}

    monkeypatch.setattr(sync, "CONFIG", _config(
        ("daily-resting-heart-rate", "mean"), ("weight", "mean")))
    monkeypatch.setattr(client, "iter_data_points", fake_points)
    with pytest.raises(sync.SyncInterrupted) as err:
        sync.run()
    assert isinstance(err.value.__cause__, ConnectionError)
    assert set(err.value.summary) == {"daily-resting-heart-rate"}
    assert sync.changed_rows(err.value.summary) == 1


def test_auth_error_is_not_wrapped(tmpdb, monkeypatch):
    def fake_points(*a, **k):
        raise auth.ReauthRequired("login")
        yield  # pragma: no cover

    monkeypatch.setattr(sync, "CONFIG", _config(("weight", "mean")))
    monkeypatch.setattr(client, "iter_data_points", fake_points)
    with pytest.raises(auth.ReauthRequired):
        sync.run()


def test_clean_run_exits_zero():
    assert sync.exit_code({"steps": {"fetched": 1, "inserted": 1}}) == 0


def test_devices_upserted(tmpdb, monkeypatch):
    monkeypatch.setattr(sync, "CONFIG", _config())
    resp = {"pairedDevices": [{"name": "users/me/pairedDevices/abc", "deviceType": "TRACKER",
                               "deviceVersion": "Synthetic 1"}]}
    monkeypatch.setattr(client, "list_paired_devices", lambda: resp)
    sync.run()
    sync.run()  # idempotent
    with sqlite3.connect(tmpdb) as conn:
        rows = conn.execute("SELECT id, display_name FROM devices").fetchall()
    assert rows == [("users/me/pairedDevices/abc", "Synthetic 1")]


def test_device_failure_is_recorded_not_fatal(tmpdb, monkeypatch):
    def boom():
        raise client.HealthApiError("403: scope")

    monkeypatch.setattr(sync, "CONFIG", _config())
    monkeypatch.setattr(client, "list_paired_devices", boom)
    result = sync.run()
    assert "error" in result["_devices"]


def test_scopes_include_profile_and_settings():
    cfg = yaml.safe_load((REPO / "config" / "health.yaml").read_text())
    assert {"profile", "settings"} <= set(cfg["scope_categories"])
    assert all(s.endswith(".readonly") for s in auth.scopes())


def test_get_user_settings_renamed():
    assert hasattr(client, "get_user_settings")
    assert not hasattr(client, "get_settings")


def _camel(data_type: str) -> str:
    return "".join(w.capitalize() if i else w for i, w in enumerate(data_type.split("-")))


def _synthetic_points(data_type: str, day: date) -> list[dict]:
    kind = client.TIME_FIELD.get(data_type, "interval")
    camel = _camel(data_type)
    if data_type in ("sleep", "exercise"):
        return [{camel: {"interval": {"startTime": f"{day.isoformat()}T06:00:00Z",
                                      "endTime": f"{day.isoformat()}T07:00:00Z"}}}]
    if kind == "daily":
        return [{camel: {"date": _ymd(day), "beatsPerMinute": "60",
                         "averageHeartRateVariabilityMilliseconds": 40.0,
                         "averagePercentage": 96.0, "breathsPerMinute": 15.0,
                         "nightlyTemperatureCelsius": 34.0, "vo2Max": 40.0}}]
    return [{camel: {"sampleTime": {"physicalTime": f"{day.isoformat()}T{h:02d}:00:00Z"},
                     "percentage": 96.0,
                     "rootMeanSquareOfSuccessiveDifferencesMilliseconds": 40.0,
                     "weightGrams": 70000.0,
                     "fullSleepStats": {"breathsPerMinute": 15.0}}} for h in range(0, 24, 2)]


def test_db_stays_under_50mb_for_200_synthetic_days(tmpdb, monkeypatch):
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(200)]
    cfg = yaml.safe_load((REPO / "config" / "health.yaml").read_text())
    cfg["initial_backfill_days"] = 400
    monkeypatch.setattr(sync, "CONFIG", cfg)

    def rollups(data_type, lo, hi):
        for d in days:
            yield {"civilStartTime": _civil(d), _camel(data_type): {"countSum": "1000"}}

    def window_rollups(data_type, lo, hi):
        for d in days:
            yield {"startTime": f"{d.isoformat()}T00:00:00Z",
                   "heartRate": {"beatsPerMinuteAvg": 70.0}}

    def points(data_type, s, e):
        for d in days:
            yield from _synthetic_points(data_type, d)

    monkeypatch.setattr(client, "iter_daily_rollups", rollups)
    monkeypatch.setattr(client, "iter_window_rollups", window_rollups)
    monkeypatch.setattr(client, "iter_data_points", points)
    result = sync.run()
    assert not [t for t, s in result.items() if "error" in s]
    assert tmpdb.stat().st_size < 50 * 1024 * 1024


def test_summed_types_all_stored_via_rollup():
    # every summed type is stored from dailyRollUp
    assert reconcile.SUMMED_TYPES <= client.ROLLUP_TYPES


# --- extract handlers for the extra types (synthetic values, real shapes) ---

def _daily(section: str, **fields) -> dict:
    return {section: {"date": _ymd(date(2026, 10, 1)), **fields}}


@pytest.mark.parametrize(("data_type", "point", "expected"), [
    ("daily-heart-rate-variability",
     _daily("dailyHeartRateVariability", averageHeartRateVariabilityMilliseconds=42.5),
     (42.5, "ms")),
    ("daily-oxygen-saturation",
     _daily("dailyOxygenSaturation", averagePercentage=96.5), (96.5, "percent")),
    ("daily-respiratory-rate",
     _daily("dailyRespiratoryRate", breathsPerMinute=14.5), (14.5, "breaths/min")),
    ("daily-sleep-temperature-derivations",
     _daily("dailySleepTemperatureDerivations", nightlyTemperatureCelsius=34.25),
     (34.25, "celsius")),
    ("daily-vo2-max", _daily("dailyVo2Max", vo2Max=41.0), (41.0, "ml/kg/min")),
    ("respiratory-rate-sleep-summary",
     {"respiratoryRateSleepSummary": {
         "sampleTime": {"physicalTime": "2026-10-01T02:00:00Z"},
         "fullSleepStats": {"breathsPerMinute": 15.25, "standardDeviation": 1.0}}},
     (15.25, "breaths/min")),
])
def test_extract_value_for_extra_daily_types(data_type, point, expected):
    assert client.extract_value(data_type, point) == expected
    start, _ = client.extract_time(data_type, point)
    assert start.startswith("2026-10-01")


def test_sleep_summary_without_full_stats_is_none():
    point = {"respiratoryRateSleepSummary": {
        "sampleTime": {"physicalTime": "2026-10-01T02:00:00Z"}}}
    assert client.extract_value("respiratory-rate-sleep-summary", point) == (None, None)


@pytest.mark.parametrize(("data_type", "section", "expected"), [
    ("floors", {"countSum": "12"}, (12.0, "count")),
    ("active-zone-minutes",
     {"sumInCardioHeartZone": "3", "sumInPeakHeartZone": "2", "sumInFatBurnHeartZone": "10"},
     (15.0, "minutes")),
    ("sedentary-period", {"durationSum": "3600s"}, (60.0, "minutes")),
    ("time-in-heart-rate-zone",
     {"timeInHeartRateZones": [{"heartRateZone": "LIGHT", "duration": "600s"},
                               {"heartRateZone": "MODERATE", "duration": "1200s"}]},
     (30.0, "minutes")),
])
def test_extract_rollup_value_for_extra_summed_types(data_type, section, expected):
    bucket = {"civilStartTime": _civil(date(2026, 10, 1)), _camel(data_type): section}
    assert client.extract_rollup_value(data_type, bucket) == expected


def test_filter_fields_for_extra_types():
    f = client.build_filter("daily-heart-rate-variability", "2026-10-01T00:00:00Z",
                            "2026-10-05T00:00:00Z")
    assert 'daily_heart_rate_variability.date >= "2026-10-01"' in f
    f = client.build_filter("respiratory-rate-sleep-summary", "2026-10-01T00:00:00Z",
                            "2026-10-05T00:00:00Z")
    assert "respiratory_rate_sleep_summary.sample_time.physical_time" in f
