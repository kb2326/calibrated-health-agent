"""Corrected associations between wearable metrics and journal outcomes.

Replaces the retired Phase 0 correlation loop, which ran hundreds of uncorrected Pearson
tests on autocorrelated series. Here, for each metric, target and lag (0 = same day,
1 = metric the day before):

- pairs are (metric on D - lag, outcome on D), metric days only when worn for its family;
- both series are first-differenced over consecutive calendar days (a pair needs D and
  D - 1 on both sides), which removes slow trends that make unrelated series correlate;
- Spearman's rho on the differences, with a two-sided permutation p-value (seeded, so a
  re-run reproduces it);
- Benjamini–Hochberg q-values across every test in the run; pairs with n < min_n are
  dropped before correction.

Results are always associations, never causes.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date, timedelta

import numpy as np

from health_ledger import wear

METRICS = {  # metric -> wear family
    "daily-heart-rate-variability": "overnight",
    "daily-resting-heart-rate": "overnight",
    "sleep": "sleep",
    "steps": "day",
}
TARGETS = ("mood", "energy", "soreness")
PERMUTATIONS = 2000
SEED = 20261023


def benjamini_hochberg(p: Sequence[float]) -> list[float]:
    """BH-adjusted q-values, in the input order."""
    m = len(p)
    order = sorted(range(m), key=lambda i: p[i])
    q = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, p[i] * m / rank)
        q[i] = running
    return q


def _ranks(x: np.ndarray) -> np.ndarray:
    order = x.argsort(kind="mergesort")
    ranks = np.empty(len(x))
    ranks[order] = np.arange(len(x))
    for value in np.unique(x):  # average ranks for ties
        tied = x == value
        ranks[tied] = ranks[tied].mean()
    return ranks


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a - a.mean(), b - b.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / denom) if denom else 0.0


def spearman(x: Sequence[float], y: Sequence[float]) -> tuple[float, float]:
    """(rho, two-sided permutation p-value)."""
    rx, ry = _ranks(np.asarray(x, float)), _ranks(np.asarray(y, float))
    rho = _corr(rx, ry)
    rng = np.random.default_rng(SEED)
    hits = sum(abs(_corr(rx, rng.permutation(ry))) >= abs(rho) - 1e-12
               for _ in range(PERMUTATIONS))
    return rho, (hits + 1) / (PERMUTATIONS + 1)


def _metric_series(conn: sqlite3.Connection, metric: str) -> dict[date, float]:
    rows = list(conn.execute("SELECT date, agg_value FROM daily_metrics WHERE data_type = ?",
                             (metric,)))
    if not rows:
        return {}
    days = [date.fromisoformat(d) for d, _ in rows]
    worn = wear.worn_days(conn, METRICS[metric], min(days), max(days))
    return {day: value for day, (_, value) in zip(days, rows, strict=True) if day in worn}


def _outcomes(conn: sqlite3.Connection, target: str) -> dict[date, float]:
    return {date.fromisoformat(d): float(v)
            for d, v in conn.execute(f"SELECT date, {target} FROM journal_outcome")}


def run(conn: sqlite3.Connection, targets: Sequence[str] = TARGETS,
        lags: Sequence[int] = (0, 1), min_n: int = 10) -> list[dict]:
    results: list[dict] = []
    outcomes = {t: _outcomes(conn, t) for t in targets}
    for metric in METRICS:
        series = _metric_series(conn, metric)
        for target in targets:
            y = outcomes[target]
            for lag in lags:
                dx, dy = [], []
                for day in sorted(y):
                    prev = day - timedelta(days=1)
                    xs = (day - timedelta(days=lag), prev - timedelta(days=lag))
                    if prev in y and xs[0] in series and xs[1] in series:
                        dx.append(series[xs[0]] - series[xs[1]])
                        dy.append(y[day] - y[prev])
                if len(dx) < min_n:
                    continue
                rho, p = spearman(dx, dy)
                results.append({"metric": metric, "target": target, "lag": lag,
                                "rho": rho, "n": len(dx), "p": p})
    for row, q in zip(results, benjamini_hochberg([r["p"] for r in results]), strict=True):
        row["q"] = q
    return results


def mean_diff_permutation(cond: Sequence[float], other: Sequence[float]) -> tuple[float, float]:
    """(mean(cond) - mean(other), two-sided permutation p-value), seeded like `spearman`."""
    a, b = np.asarray(cond, float), np.asarray(other, float)
    effect = float(a.mean() - b.mean())
    pooled = np.concatenate([a, b])
    rng = np.random.default_rng(SEED)
    hits = 0
    for _ in range(PERMUTATIONS):
        perm = rng.permutation(pooled)
        hits += abs(perm[:len(a)].mean() - perm[len(a):].mean()) >= abs(effect) - 1e-12
    return effect, (hits + 1) / (PERMUTATIONS + 1)
