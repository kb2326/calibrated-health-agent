"""The morning lock: one atomic, hash-chained set of bets per day."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from health_ledger import chain, dist, lock
from health_ledger.forecasters import Forecast
from ledger_fixtures import make_db, metric

D = date(2026, 10, 30)


def ist(hour: int, minute: int = 0) -> datetime:
    """An instant at hour:minute on D in Asia/Kolkata (UTC+05:30)."""
    total = hour * 60 + minute - 330
    return datetime(2026, 10, 30, 0, 0, tzinfo=UTC).replace(hour=total // 60, minute=total % 60)


def _uniform(conn, day, snap):
    return Forecast(probs=dict.fromkeys(("mood", "energy", "soreness"), tuple([0.1] * 10)))


def _shy(conn, day, snap):
    return Forecast(probs={"mood": tuple([0.1] * 10)},
                    abstain={"energy": "not enough data", "soreness": "not enough data"})


def _broken(conn, day, snap):
    raise RuntimeError("boom 7")


FAKES = {"a": _uniform, "b": _shy, "c": _broken}


@pytest.fixture
def conn(tmp_path):
    c = make_db(tmp_path / "t.db")
    chain.ensure_plan_hash(c, "ab")
    yield c
    c.close()


def test_lock_due_on_sleep_or_noon(conn):
    assert lock.due(conn, ist(9)) is False
    assert lock.due(conn, ist(12)) is True
    metric(conn, D, "sleep", 400)
    assert lock.due(conn, ist(9)) is True


def test_lock_writes_snapshot_forecasts_and_chain(conn):
    result = lock.lock_today(conn, ist(12, 5), FAKES)
    assert result == {"day": "2026-10-30", "forecasters": 3, "abstained": 5,
                      "missing_inputs": 6}
    rows = conn.execute("SELECT forecaster, target, probs_json, abstain_reason FROM forecasts "
                        "ORDER BY forecaster, target").fetchall()
    assert len(rows) == 9
    assert ("a", "energy", json.dumps([0.1] * 10), None) in rows
    assert ("c", "mood", None, "error: RuntimeError") in rows
    snap = conn.execute("SELECT snapshot_hash, missing_json FROM snapshots").fetchone()
    payload = json.loads(conn.execute("SELECT payload_json FROM ledger WHERE kind='lock'").fetchone()[0])
    assert payload["snapshot_hash"] == snap[0] and len(payload["forecasts_hash"]) == 64
    assert chain.verify(conn) == []


def test_lock_is_idempotent(conn):
    assert lock.lock_today(conn, ist(12), FAKES) is not None
    counts = [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("snapshots", "forecasts", "ledger")]
    assert lock.lock_today(conn, ist(13), FAKES) is None
    assert counts == [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in ("snapshots", "forecasts", "ledger")]


def test_forecaster_exception_abstains_not_crashes(conn):
    lock.lock_today(conn, ist(12), {"c": _broken})
    reasons = {r[0] for r in conn.execute("SELECT abstain_reason FROM forecasts")}
    assert reasons == {"error: RuntimeError"}


def test_missing_target_is_recorded_as_abstain(conn):
    lock.lock_today(conn, ist(12), {"x": lambda c, d, s: Forecast(probs={"mood": tuple([0.1] * 10)})})
    reasons = dict(conn.execute("SELECT target, abstain_reason FROM forecasts WHERE probs_json IS NULL"))
    assert reasons == {"energy": "no forecast returned", "soreness": "no forecast returned"}


def test_lock_is_atomic(conn, monkeypatch):
    def fail(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(lock.chain, "append", fail)
    with pytest.raises(RuntimeError):
        lock.lock_today(conn, ist(12), FAKES)
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM ledger WHERE kind='lock'").fetchone()[0] == 0


def test_stored_probabilities_round_trip(conn):
    lock.lock_today(conn, ist(12), {"a": _uniform})
    stored = json.loads(conn.execute("SELECT probs_json FROM forecasts LIMIT 1").fetchone()[0])
    assert dist.normalize(stored) == pytest.approx(tuple([0.1] * 10))
