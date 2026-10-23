"""Settling locked days: score, void, or record that no outcome came."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from health_ledger import chain, dist, lock, outcomes
from health_ledger.forecasters import Forecast
from ledger_fixtures import journal, make_db

D = date(2026, 10, 30)
LOCK_AT = datetime(2026, 10, 30, 6, 30, tzinfo=UTC)  # 12:00 IST


def _uniform(conn, day, snap):
    return Forecast(probs=dict.fromkeys(("mood", "energy", "soreness"), tuple([0.1] * 10)))


def _shy(conn, day, snap):
    return Forecast(probs={"energy": dist.discretized_normal(7, 1)},
                    abstain={"mood": "x", "soreness": "x"})


@pytest.fixture
def conn(tmp_path):
    c = make_db(tmp_path / "t.db")
    chain.ensure_plan_hash(c, "ab")
    lock.lock_today(c, LOCK_AT, {"a": _uniform, "b": _shy})
    yield c
    c.close()


def _kinds(conn):
    return [r[0] for r in conn.execute("SELECT kind FROM ledger ORDER BY seq")]


def test_scores_written_for_each_forecaster_and_target(conn):
    journal(conn, D, 6, 7, 2, submitted_at="2026-10-30T14:30:00.000000Z")  # 20:00 IST
    assert outcomes.settle(conn, datetime(2026, 10, 30, 17, 0, tzinfo=UTC)) == {
        "scored": 1, "voided": 0, "no_outcome": 0}
    rows = {(f, t): (o, r) for f, t, o, r in conn.execute(
        "SELECT forecaster, target, outcome, rps FROM scores")}
    assert set(rows) == {("a", "mood"), ("a", "energy"), ("a", "soreness"), ("b", "energy")}
    assert rows[("a", "energy")] == (7, pytest.approx(dist.rps(tuple([0.1] * 10), 7)))
    payload = json.loads(conn.execute("SELECT payload_json FROM ledger WHERE kind='outcome'").fetchone()[0])
    row_hash = conn.execute("SELECT row_hash FROM journal_submissions").fetchone()[0]
    assert payload["outcome_row_hash"] == row_hash and len(payload["scores_hash"]) == 64
    assert chain.verify(conn) == []


def test_abstained_forecasts_not_scored(conn):
    journal(conn, D, 6, 7, 2, submitted_at="2026-10-30T14:30:00.000000Z")
    outcomes.settle(conn, datetime(2026, 10, 30, 17, 0, tzinfo=UTC))
    assert conn.execute("SELECT COUNT(*) FROM scores WHERE forecaster='b'").fetchone()[0] == 1


def test_outcome_before_lock_voids_day(conn):
    journal(conn, D, 6, 7, 2, submitted_at="2026-10-30T05:00:00.000000Z")  # 10:30 IST, pre-lock
    assert outcomes.settle(conn, datetime(2026, 10, 30, 17, 0, tzinfo=UTC))["voided"] == 1
    assert _kinds(conn)[-1] == "void"
    assert conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == 0


def test_unsettled_before_deadline(conn):
    assert outcomes.settle(conn, datetime(2026, 10, 30, 23, 0, tzinfo=UTC)) == {
        "scored": 0, "voided": 0, "no_outcome": 0}  # 04:30 IST on D+1, before 06:00
    assert _kinds(conn) == ["plan", "lock"]


def test_no_outcome_after_deadline(conn):
    assert outcomes.settle(conn, datetime(2026, 10, 31, 0, 30, tzinfo=UTC))["no_outcome"] == 1
    assert _kinds(conn)[-1] == "no_outcome"


def test_scoring_is_idempotent(conn):
    journal(conn, D, 6, 7, 2, submitted_at="2026-10-30T14:30:00.000000Z")
    later = datetime(2026, 10, 31, 3, 0, tzinfo=UTC)
    outcomes.settle(conn, later)
    assert outcomes.settle(conn, later) == {"scored": 0, "voided": 0, "no_outcome": 0}
    assert conn.execute("SELECT COUNT(*) FROM ledger WHERE kind='outcome'").fetchone()[0] == 1


def test_late_submission_does_not_count(conn):
    journal(conn, D, 6, 7, 2, submitted_at="2026-10-31T02:00:00.000000Z", status="late")
    assert outcomes.settle(conn, datetime(2026, 10, 31, 3, 0, tzinfo=UTC))["no_outcome"] == 1
