"""Phase 4.5: the additional Google Health API types (research 11, probe 2026-10-31)."""
from __future__ import annotations

import pytest
from health_data import client
from health_data.sync import CONFIG

NEW_SAMPLE = ("vo2-max", "run-vo2-max", "body-fat", "height", "blood-glucose",
              "core-body-temperature")
NEW_INTERVAL = ("active-energy-burned", "activity-level", "altitude", "swim-lengths-data")


def test_new_types_are_configured_and_filtered_by_kind():
    for t in (*NEW_SAMPLE, *NEW_INTERVAL, "daily-heart-rate-zones", "calories-in-heart-rate-zone"):
        assert t in CONFIG["data_types"], t
    for t in NEW_SAMPLE:
        assert client.filter_path(t) == f"{t.replace('-', '_')}.sample_time.physical_time"
    assert client.filter_path("daily-heart-rate-zones") == "daily_heart_rate_zones.date"
    assert "calories-in-heart-rate-zone" in client.ROLLUP_TYPES
    for t in NEW_INTERVAL:
        assert client.filter_path(t) == f"{t.replace('-', '_')}.interval.civil_start_time"


@pytest.mark.parametrize(("data_type", "point", "value", "unit"), [
    ("vo2-max", {"vo2Max": {"vo2Max": 44.5}}, 44.5, "ml/kg/min"),
    ("run-vo2-max", {"runVo2Max": {"runVo2Max": 46.0}}, 46.0, "ml/kg/min"),
    ("body-fat", {"bodyFat": {"percentage": 18.2}}, 18.2, "percent"),
    ("height", {"height": {"heightMillimeters": "1745"}}, 1.745, "m"),
    ("blood-glucose", {"bloodGlucose": {"bloodGlucoseMilligramsPerDeciliter": 96}}, 96.0, "mg/dL"),
    ("core-body-temperature", {"coreBodyTemperature": {"temperatureCelsius": 36.8}}, 36.8,
     "celsius"),
    ("active-energy-burned", {"activeEnergyBurned": {"kcal": 12.5}}, 12.5, "kcal"),
    ("altitude", {"altitude": {"gainMillimeters": "3000"}}, 3.0, "m"),
    ("swim-lengths-data", {"swimLengthsData": {"strokeCount": "18", "swimStrokeType": "FREESTYLE"}},
     18.0, "strokes"),
])
def test_new_types_extract_their_value(data_type, point, value, unit):
    got, got_unit = client.extract_value(data_type, point)
    assert got == pytest.approx(value) and got_unit == unit


def test_activity_level_and_zone_thresholds_have_no_daily_scalar():
    # kept as raw_json only; the v5 derive step reads them
    assert client.extract_value("activity-level",
                                {"activityLevel": {"activityLevelType": "LIGHTLY_ACTIVE"}}) == (None, None)
    assert client.extract_value("daily-heart-rate-zones", {"dailyHeartRateZones": {
        "heartRateZones": [{"heartRateZoneType": "PEAK", "minBeatsPerMinute": 160}]}}) == (None, None)


def test_calories_in_zone_rollup_sums_every_zone():
    bucket = {"caloriesInHeartRateZone": {"caloriesInHeartRateZones": [
        {"heartRateZone": "CARDIO", "kcal": 120.5}, {"heartRateZone": "PEAK", "kcal": 30}]}}
    assert client.extract_rollup_value("calories-in-heart-rate-zone", bucket) == (150.5, "kcal")
