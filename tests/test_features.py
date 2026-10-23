"""The feature snapshot every forecaster gets: same inputs, no leakage from day D's outcome."""
from __future__ import annotations

from datetime import date, timedelta

from health_ledger import features
from ledger_fixtures import journal, make_db, metric

D = date(2026, 10, 30)  # a Friday


def test_snapshot_never_reads_journal_for_day_itself(tmp_path):
    conn = make_db(tmp_path / "t.db")
    journal(conn, D - timedelta(days=1), 6, 7, 2)
    journal(conn, D, 1, 1, 9)  # the answer being forecast must stay invisible
    snap, _ = features.snapshot(conn, D)
    assert snap["journal_prev_day"] == {"mood": 6, "energy": 7, "soreness": 2}
    assert snap["journal_last7"] == {"mood": [6], "energy": [7], "soreness": [2]}
    assert snap["journal_days_total"] == 1


def test_snapshot_lists_missing_inputs(tmp_path):
    conn = make_db(tmp_path / "t.db")
    metric(conn, D, "sleep", 420)
    metric(conn, D - timedelta(days=1), "steps", 5000)
    snap, missing = features.snapshot(conn, D)
    assert snap["sleep_minutes"] == 420 and snap["steps_prev_day"] == 5000
    assert snap["weekday"] == 4 and snap["day"] == "2026-10-30"
    assert set(missing) == {"hrv_rmssd", "resting_hr", "readiness", "journal_prev_day"}
    assert all(snap[k] is None for k in missing)


def test_snapshot_ignores_unworn_and_apple_hrv(tmp_path):
    conn = make_db(tmp_path / "t.db")
    metric(conn, D, "sleep", 90)  # not a worn night
    metric(conn, D, "daily-heart-rate-variability", 55, "HEALTH_KIT")
    metric(conn, D - timedelta(days=1), "steps", 200)  # not a worn day
    snap, missing = features.snapshot(conn, D)
    assert snap["sleep_minutes"] is None and snap["hrv_rmssd"] is None
    assert snap["steps_prev_day"] is None
    assert {"sleep_minutes", "hrv_rmssd", "steps_prev_day"} <= set(missing)


def test_snapshot_does_not_see_daytime_totals_of_day_itself(tmp_path):
    conn = make_db(tmp_path / "t.db")
    metric(conn, D, "steps", 9000)  # today's steps are not known at the morning lock
    snap, _ = features.snapshot(conn, D)
    assert snap["steps_prev_day"] is None


def test_canonical_hash_stable_across_key_order():
    a = features.canonical({"b": 1, "a": [1, 2], "c": {"y": None, "x": "é"}})
    b = features.canonical({"c": {"x": "é", "y": None}, "a": [1, 2], "b": 1})
    assert a == b == '{"a":[1,2],"b":1,"c":{"x":"é","y":null}}'
    assert features.sha256(a) == features.sha256(b) and len(features.sha256(a)) == 64
