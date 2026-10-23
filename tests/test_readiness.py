"""Open readiness score: a documented counterpart of proprietary recovery scores."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from health_ledger import readiness
from ledger_fixtures import make_db, metric

D = date(2026, 10, 30)


@pytest.fixture
def conn(tmp_path):
    c = make_db(tmp_path / "t.db")
    for i in range(1, 15):  # two weeks of worn history with some spread
        day = D - timedelta(days=i)
        metric(c, day, "daily-heart-rate-variability", 40 + (i % 5), "FITBIT")
        metric(c, day, "daily-resting-heart-rate", 60 + (i % 3), "FITBIT")
        metric(c, day, "sleep", 400 + 10 * (i % 4))
    yield c
    c.close()


def test_readiness_none_with_one_component(conn):
    metric(conn, D, "sleep", 450)
    result = readiness.score(conn, D)
    assert result["score"] is None and result["n_components"] == 1


def test_readiness_high_when_hrv_up_rhr_down(conn):
    metric(conn, D, "daily-heart-rate-variability", 60, "FITBIT")
    metric(conn, D, "daily-resting-heart-rate", 55, "FITBIT")
    result = readiness.score(conn, D)
    assert result["n_components"] == 2
    assert result["components"]["hrv_z"] > 0 and result["components"]["rhr_z"] < 0
    assert result["score"] is not None and result["score"] > 50


def test_readiness_low_when_hrv_down(conn):
    metric(conn, D, "daily-heart-rate-variability", 20, "FITBIT")
    metric(conn, D, "daily-resting-heart-rate", 70, "FITBIT")
    metric(conn, D, "sleep", 300)
    result = readiness.score(conn, D)
    assert result["n_components"] == 3 and result["score"] is not None and result["score"] < 50


def test_readiness_is_clipped_to_0_100(conn):
    metric(conn, D, "daily-heart-rate-variability", 500, "FITBIT")
    metric(conn, D, "daily-resting-heart-rate", 20, "FITBIT")
    assert readiness.score(conn, D)["score"] == 100


def test_short_sleep_is_not_a_component(conn):
    metric(conn, D, "sleep", 120)  # not worn for sleep
    metric(conn, D, "daily-resting-heart-rate", 60, "FITBIT")
    assert readiness.score(conn, D)["components"]["sleep_z"] is None
