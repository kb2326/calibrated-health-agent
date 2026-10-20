"""Contract tests for the Google Health API client.

Every test here corresponds to a bug that reached production data. The API
fails *silently* on a wrong assumption — a bad filter field returns an empty
page rather than an error, a mis-read timestamp collapses 740,000 points into
one row — so these assertions are the only thing standing between a wrong
guess and a corrupted substrate.
"""
from __future__ import annotations

import pytest
from health_data import client

# --- filter construction ------------------------------------------------
# The list endpoint has no startTime/endTime; it takes one AIP-160 filter and
# the field differs per data type. Getting this wrong returns HTTP 400.

class TestFilterConstruction:
    def test_sample_type_uses_physical_time_with_zone(self):
        f = client.build_filter("heart-rate", "2026-07-21T10:30:00+00:00", "2026-08-20T10:30:00+00:00")
        assert "heart_rate.sample_time.physical_time" in f
        assert "+00:00" in f, "physical-time fields require an explicit zone"

    def test_interval_type_uses_civil_time_without_zone(self):
        f = client.build_filter("steps", "2026-07-21T10:30:00+00:00", "2026-08-20T10:30:00+00:00")
        assert "steps.interval.civil_start_time" in f
        assert "+00:00" not in f and "Z" not in f, "civil fields reject a timezone designator"

    def test_daily_type_compares_bare_dates(self):
        f = client.build_filter("daily-resting-heart-rate", "2026-07-21T10:30:00+00:00", "2026-08-20T10:30:00+00:00")
        assert 'daily_resting_heart_rate.date >= "2026-07-21"' in f
        assert "T" not in f.split(">=")[1], "daily fields take a date, not a datetime"

    def test_sleep_overrides_to_civil_end_time(self):
        # sleep is the one type that filters on when the session ended
        f = client.build_filter("sleep", "2026-07-21T10:30:00+00:00", "2026-08-20T10:30:00+00:00")
        assert "sleep.interval.civil_end_time" in f

    def test_range_is_half_open(self):
        # The API supports only >= and <. A closed range would double-count
        # the boundary row on the next incremental sync.
        f = client.build_filter("steps", "2026-07-21T00:00:00Z", "2026-08-20T00:00:00Z")
        assert ">=" in f and " < " in f
        assert "<=" not in f


# --- timestamp extraction -----------------------------------------------
# v4 nests the timestamp inside the type section. Reading a non-existent
# top-level "startTime" yielded "" for every point, and the raw_points UNIQUE
# constraint then discarded 739,824 of 739,827 rows without any error.

class TestTimeExtraction:
    def test_sample_type_reads_nested_sample_time(self):
        point = {"heartRate": {"sampleTime": {"physicalTime": "2026-08-19T14:25:40Z"}, "beatsPerMinute": "125"}}
        start, end = client.extract_time("heart-rate", point)
        assert start == "2026-08-19T14:25:40Z"
        assert end == start, "an instantaneous sample has no duration"

    def test_interval_type_reads_both_bounds(self):
        point = {"sleep": {"interval": {"startTime": "2026-08-17T18:47:00Z", "endTime": "2026-08-18T02:03:00Z"}}}
        start, end = client.extract_time("sleep", point)
        assert start == "2026-08-17T18:47:00Z"
        assert end == "2026-08-18T02:03:00Z"

    def test_daily_type_reads_date_parts(self):
        point = {"dailyRestingHeartRate": {"date": {"year": 2026, "month": 8, "day": 18}, "beatsPerMinute": "65"}}
        assert client.extract_time("daily-resting-heart-rate", point) == ("2026-08-18", "2026-08-18")

    def test_no_top_level_start_time_is_ever_consulted(self):
        # Regression guard: the old code read point["startTime"]. If anyone
        # reintroduces that, this decoy would be picked up.
        point = {"startTime": "1999-01-01T00:00:00Z",
                 "heartRate": {"sampleTime": {"physicalTime": "2026-08-19T14:25:40Z"}}}
        start, _ = client.extract_time("heart-rate", point)
        assert start == "2026-08-19T14:25:40Z"

    def test_unparseable_point_yields_empty_not_crash(self):
        assert client.extract_time("heart-rate", {"heartRate": {}}) == ("", "")


# --- value extraction ---------------------------------------------------

class TestValueExtraction:
    def test_int64_arrives_as_a_json_string(self):
        # Protobuf serialises int64 as a string. The original isinstance(
        # v, (int, float)) guard rejected every heart-rate reading.
        point = {"heartRate": {"beatsPerMinute": "125"}}
        assert client.extract_value("heart-rate", point) == (125.0, "bpm")

    def test_weight_converts_grams_to_kilograms(self):
        point = {"weight": {"weightGrams": 82000}}
        value, unit = client.extract_value("weight", point)
        assert value == pytest.approx(82.0)
        assert unit == "kg"

    def test_duration_types_derive_minutes_from_interval(self):
        point = {"sleep": {"interval": {"startTime": "2026-08-17T18:47:00Z", "endTime": "2026-08-18T02:03:00Z"}}}
        value, unit = client.extract_value("sleep", point)
        assert value == pytest.approx(436.0)  # 7h16m
        assert unit == "minutes"

    def test_zero_is_treated_as_absent_not_as_a_reading(self):
        # Apple HealthKit reports HRV as SDNN and leaves RMSSD at 0. Eight
        # such points dragged a day's mean to 0.0 and fired a -3.55 sigma
        # false alert.
        point = {"heartRateVariability": {
            "rootMeanSquareOfSuccessiveDifferencesMilliseconds": 0,
            "standardDeviationMilliseconds": 50.14,
        }}
        assert client.extract_value("heart-rate-variability", point) == (None, None)

    def test_genuine_hrv_reading_is_kept(self):
        point = {"heartRateVariability": {"rootMeanSquareOfSuccessiveDifferencesMilliseconds": 38.3}}
        assert client.extract_value("heart-rate-variability", point) == (38.3, "ms")


# --- query-range chunking -----------------------------------------------

class TestQueryRangeCaps:
    def test_capped_types_are_split_into_compliant_windows(self):
        assert client.LIST_MAX_DAYS["heart-rate"] == 14
        assert client.LIST_MAX_DAYS["total-calories"] == 14

    def test_uncapped_types_use_the_ninety_day_default(self):
        assert client.LIST_MAX_DAYS.get("weight", client.LIST_DEFAULT_MAX_DAYS) == 90

    def test_empty_window_yields_nothing_rather_than_calling_the_api(self):
        # A same-day re-sync of a daily type produced
        # date >= "X" AND date < "X", which the API rejects outright.
        same = "2026-08-21T09:00:00+00:00"
        got = list(client.iter_data_points("daily-resting-heart-rate", same, same))
        assert got == []

    def test_reversed_window_yields_nothing(self):
        got = list(client.iter_data_points("weight", "2026-08-21T00:00:00Z", "2026-08-01T00:00:00Z"))
        assert got == []


# --- read-only guardrail ------------------------------------------------

class _FakeRequest:
    """Stands in for a googleapiclient HttpRequest."""

    def __init__(self, method_id):
        if method_id is not None:
            self.methodId = method_id

    def execute(self):  # pragma: no cover - must never be reached in these tests
        raise AssertionError("a refused request must never be executed")


class TestReadOnlyGuardrail:
    def test_mislabelled_write_is_refused(self):
        # The guard used to check only the caller's string label, so a write
        # request carrying a read label passed straight through.
        with pytest.raises(client.HealthApiError, match="not in the read-only allowlist"):
            client._read("dataPoints.list", _FakeRequest("health.users.dataTypes.dataPoints.create"))

    @pytest.mark.parametrize("method", [
        "health.users.dataTypes.dataPoints.create",
        "health.users.dataTypes.dataPoints.patch",
        "health.users.dataTypes.dataPoints.batchDelete",
        "health.users.updateProfile",
        "health.users.updateSettings",
    ])
    def test_every_mutating_method_is_refused(self, method):
        with pytest.raises(client.HealthApiError):
            client._read(method.rsplit(".", 1)[-1], _FakeRequest(method))

    def test_request_without_method_id_is_refused(self):
        with pytest.raises(client.HealthApiError, match="no methodId"):
            client._read("dataPoints.list", _FakeRequest(None))

    def test_label_must_match_the_request(self):
        with pytest.raises(client.HealthApiError, match="mismatch"):
            client._read("dataPoints.get", _FakeRequest("health.users.dataTypes.dataPoints.list"))

    def test_allowlist_contains_no_mutating_verb(self):
        forbidden = ("create", "patch", "delete", "update", "batchDelete")
        for method in client.READ_METHODS:
            assert not any(method.lower().endswith(v.lower()) for v in forbidden), method
