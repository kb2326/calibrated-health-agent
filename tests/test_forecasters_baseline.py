"""Forecasters 1-4: the simple rules the agent has to beat, and the statistical model."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from health_ledger import features, forecasters
from health_ledger.forecasters import baselines, statistical
from ledger_fixtures import journal, make_db, metric

D = date(2026, 10, 30)
TARGETS = ("mood", "energy", "soreness")


@pytest.fixture
def conn(tmp_path):
    c = make_db(tmp_path / "t.db")
    yield c
    c.close()


def _run(name, conn, day=D):
    snap, _ = features.snapshot(conn, day)
    return forecasters.FORECASTERS[name](conn, day, snap)


def test_registry_order():
    assert list(forecasters.FORECASTERS)[:4] == [
        "climatology", "persistence", "seasonal_naive", "statistical"]


def test_climatology_uniform_with_no_history(conn):
    f = _run("climatology", conn)
    assert f.abstain == {} and set(f.probs) == set(TARGETS)
    assert f.probs["energy"] == pytest.approx(tuple([0.1] * 10))


def test_climatology_follows_history(conn):
    for i in range(1, 6):
        journal(conn, D - timedelta(days=i), 5, 8, 2)
    p = _run("climatology", conn).probs["energy"]
    assert max(range(10), key=lambda i: p[i]) == 7


def test_persistence_centres_on_yesterday(conn):
    journal(conn, D - timedelta(days=1), 3, 9, 1)
    f = _run("persistence", conn)
    assert max(range(10), key=lambda i: f.probs["energy"][i]) == 8
    assert max(range(10), key=lambda i: f.probs["mood"][i]) == 2


def test_persistence_abstains_after_gap(conn):
    journal(conn, D - timedelta(days=4), 3, 9, 1)
    f = _run("persistence", conn)
    assert f.probs == {} and f.abstain == {t: "no outcome in last 3 days" for t in TARGETS}


def test_seasonal_uses_same_weekday(conn):
    journal(conn, D - timedelta(days=7), 2, 2, 2)
    journal(conn, D - timedelta(days=1), 9, 9, 9)
    f = _run("seasonal_naive", conn)
    assert max(range(10), key=lambda i: f.probs["energy"][i]) == 1
    assert _run("seasonal_naive", conn, D + timedelta(days=1)).abstain["energy"] == "no outcome on D-7"


def test_statistical_abstains_below_14_pairs(conn):
    f = _run("statistical", conn)
    assert f.probs == {} and set(f.abstain) == set(TARGETS)


def test_statistical_uses_readiness(conn, monkeypatch):
    scores = {D - timedelta(days=i): 30.0 + 3 * i for i in range(1, 21)}
    for day, r in scores.items():
        journal(conn, day, 5, max(1, min(10, round(r / 10))), 3)
    monkeypatch.setattr(statistical.readiness, "score", lambda c, d: {"score": scores.get(d, 90.0)})
    snap = {**features.snapshot(conn, D)[0], "readiness": 90.0}
    f = forecasters.FORECASTERS["statistical"](conn, D, snap)
    assert "energy" in f.probs
    assert max(range(10), key=lambda i: f.probs["energy"][i]) == 8  # ~9 at readiness 90
    snap["readiness"] = None
    assert forecasters.FORECASTERS["statistical"](conn, D, snap).abstain["energy"] == "readiness missing"


def test_no_forecaster_reads_outcome_of_day_itself(conn):
    journal(conn, D - timedelta(days=7), 5, 5, 5)
    journal(conn, D - timedelta(days=1), 5, 5, 5)
    before = {n: _run(n, conn) for n in ("climatology", "persistence", "seasonal_naive")}
    journal(conn, D, 10, 10, 10)  # the outcome lands after the lock
    for name, f in before.items():
        assert _run(name, conn) == f


def test_history_is_strictly_before(conn):
    journal(conn, D, 1, 1, 1)
    journal(conn, D - timedelta(days=2), 4, 4, 4)
    assert baselines.outcome_history(conn, D)["mood"] == [(D - timedelta(days=2), 4)]
    metric(conn, D, "steps", 1)  # unrelated rows do not matter
