"""Wear rules: a day only counts for a family when the watch was demonstrably worn."""
from __future__ import annotations

from datetime import date

import pytest
from health_ledger import wear
from ledger_fixtures import make_db, metric

D = date(2026, 10, 20)


@pytest.fixture
def conn(tmp_path):
    c = make_db(tmp_path / "t.db")
    yield c
    c.close()


def test_non_wear_day_is_not_worn_even_with_low_steps(conn):
    metric(conn, D, "steps", 300)
    assert wear.worn(conn, D)["day"] is False


def test_day_worn_with_resting_hr_or_enough_steps(conn):
    metric(conn, D, "steps", 1000)
    assert wear.worn(conn, D)["day"] is True
    metric(conn, date(2026, 10, 21), "daily-resting-heart-rate", 58, "FITBIT")
    assert wear.worn(conn, date(2026, 10, 21))["day"] is True


def test_short_sleep_not_worn(conn):
    metric(conn, D, "sleep", 150)
    assert wear.worn(conn, D)["sleep"] is False
    metric(conn, date(2026, 10, 21), "sleep", 180)
    assert wear.worn(conn, date(2026, 10, 21))["sleep"] is True


def test_overnight_needs_rhr_or_fitbit_hrv(conn):
    metric(conn, D, "daily-heart-rate-variability", 40, "HEALTH_KIT")
    assert wear.worn(conn, D)["overnight"] is False
    metric(conn, date(2026, 10, 21), "daily-heart-rate-variability", 40, "FITBIT")
    assert wear.worn(conn, date(2026, 10, 21))["overnight"] is True


def test_worn_days_is_inclusive_range(conn):
    for i, steps in enumerate([2000, 100, 3000]):
        metric(conn, date(2026, 10, 20 + i), "steps", steps)
    assert wear.worn_days(conn, "day", date(2026, 10, 20), date(2026, 10, 22)) == {
        date(2026, 10, 20), date(2026, 10, 22)}
