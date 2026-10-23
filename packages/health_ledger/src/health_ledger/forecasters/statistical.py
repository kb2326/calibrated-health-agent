"""Forecaster 4: a statistical model on the open readiness score.

Per target, ordinary least squares of past outcomes on that morning's readiness score,
over every past day that has both (at least 14 pairs). The forecast for D is a normal
centred on the fitted value with the residual standard deviation (floored at 0.5),
discretized onto 1..10. A linear-Gaussian model is deliberately simple: with weeks of
data, anything richer overfits.
"""
from __future__ import annotations

import sqlite3
from datetime import date

import numpy as np

from health_ledger import dist, readiness
from health_ledger.forecasters.base import Forecast
from health_ledger.forecasters.baselines import outcome_history

MIN_PAIRS = 14


def forecast(conn: sqlite3.Connection, day: date, snapshot: dict) -> Forecast:
    today = snapshot.get("readiness")
    history = outcome_history(conn, day)
    days = sorted({d for h in history.values() for d, _ in h})
    scores = {d: readiness.score(conn, d)["score"] for d in days}
    probs, abstain = {}, {}
    for target, rows in history.items():
        pairs = [(scores[d], v) for d, v in rows if scores[d] is not None]
        if len(pairs) < MIN_PAIRS:
            abstain[target] = f"fewer than {MIN_PAIRS} readiness-outcome pairs"
            continue
        if today is None:
            abstain[target] = "readiness missing"
            continue
        x, y = np.array(pairs, float).T
        slope, intercept = np.polyfit(x, y, 1)
        resid = y - (slope * x + intercept)
        sd = float(np.sqrt((resid ** 2).sum() / (len(y) - 2)))
        probs[target] = dist.discretized_normal(float(slope * today + intercept), sd)
    return Forecast(probs=probs, abstain=abstain)
