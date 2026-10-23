"""Forecasters 1-3: the simple rules every smarter forecaster has to beat.

- climatology: "my usual". The Dirichlet-smoothed distribution of all past outcomes
  (prior weight 1 per score), so with no history it is uniform and never abstains.
- persistence: "same as yesterday". The latest outcome from D-1, D-2 or D-3, spread by
  the empirical distribution of day-to-day changes.
- seasonal_naive: "same as last week". The outcome on D-7, with the same spread.

The change distribution starts from prior weights {-1: 1, 0: 2, +1: 1} and adds every
observed change between consecutive journal days, so it widens or narrows as data arrives.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from health_ledger import dist
from health_ledger.forecasters.base import TARGETS, Forecast

CHANGE_PRIOR = {-1: 1.0, 0: 2.0, 1: 1.0}
PERSISTENCE_DAYS = 3


def outcome_history(conn: sqlite3.Connection, before: date) -> dict[str, list[tuple[date, int]]]:
    """Journal outcomes strictly before `before`, oldest first, per target."""
    rows = list(conn.execute(
        "SELECT date, mood, energy, soreness FROM journal_outcome WHERE date < ? ORDER BY date",
        (before.isoformat(),)))
    return {t: [(date.fromisoformat(r[0]), int(r[i + 1])) for r in rows]
            for i, t in enumerate(TARGETS)}


def _changes(history: list[tuple[date, int]]) -> dict[int, float]:
    weights = dict(CHANGE_PRIOR)
    by_day = dict(history)
    for day, value in history:
        prev = by_day.get(day - timedelta(days=1))
        if prev is not None:
            weights[value - prev] = weights.get(value - prev, 0.0) + 1.0
    return weights


def climatology(conn: sqlite3.Connection, day: date, snapshot: dict) -> Forecast:
    probs = {}
    for target, history in outcome_history(conn, day).items():
        counts = [0] * dist.K
        for _, value in history:
            counts[value - 1] += 1
        probs[target] = dist.from_counts(counts)
    return Forecast(probs=probs)


def _anchored(conn: sqlite3.Connection, day: date, anchor_days: list[date],
              reason: str) -> Forecast:
    probs, abstain = {}, {}
    for target, history in outcome_history(conn, day).items():
        by_day = dict(history)
        anchor = next((by_day[d] for d in anchor_days if d in by_day), None)
        if anchor is None:
            abstain[target] = reason
        else:
            probs[target] = dist.shift(anchor, _changes(history))
    return Forecast(probs=probs, abstain=abstain)


def persistence(conn: sqlite3.Connection, day: date, snapshot: dict) -> Forecast:
    days = [day - timedelta(days=i) for i in range(1, PERSISTENCE_DAYS + 1)]
    return _anchored(conn, day, days, f"no outcome in last {PERSISTENCE_DAYS} days")


def seasonal_naive(conn: sqlite3.Connection, day: date, snapshot: dict) -> Forecast:
    return _anchored(conn, day, [day - timedelta(days=7)], "no outcome on D-7")
