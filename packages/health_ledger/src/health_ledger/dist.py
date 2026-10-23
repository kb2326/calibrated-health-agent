"""Probability distributions over the journal's 1..10 scale, and the scores that grade them.

A forecast is a full distribution (10 probabilities, index 0 is score 1), never a point.
Every probability is floored at 1e-4 so a confident miss costs a large but finite log
score. Scores:

- ranked probability score (RPS): mean over thresholds k = 1..9 of
  (P(score <= k) - 1[outcome <= k])^2. Ordinal-aware, 0 is perfect, lower is better.
- log score: -ln p(outcome). Punishes confident misses.
- skill vs a reference: 1 - mean_score / mean_reference. Above 0 beats the reference.

Intervals for skill use a paired moving-block bootstrap (blocks of consecutive days keep
the day-to-day dependence), seeded so a re-run reproduces the published interval.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np

K = 10
FLOOR = 1e-4
Dist = tuple[float, ...]


def normalize(p: Sequence[float], floor: float = FLOOR) -> Dist:
    if len(p) != K:
        raise ValueError(f"need {K} probabilities, got {len(p)}")
    if any(not math.isfinite(x) or x < 0 for x in p):
        raise ValueError("probabilities must be finite and non-negative")
    total = sum(p)
    if total <= 0:
        raise ValueError("probabilities sum to zero")
    floored = [max(x / total, floor) for x in p]
    total = sum(floored)
    return tuple(x / total for x in floored)


def from_counts(counts: Sequence[int], prior: float = 1.0) -> Dist:
    """Dirichlet-smoothed empirical distribution: (count + prior) / (n + 10 * prior)."""
    return normalize([c + prior for c in counts])


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def discretized_normal(mean: float, sd: float) -> Dist:
    """Mass of N(mean, sd) on [k - 0.5, k + 0.5]; both tails fold into 1 and 10."""
    sd = max(sd, 0.5)
    cdf = [_phi((k + 0.5 - mean) / sd) for k in range(1, K)]  # P(X <= k + 0.5), k = 1..9
    edges = [0.0, *cdf, 1.0]
    return normalize([edges[i + 1] - edges[i] for i in range(K)])


def shift(center: int, delta: Mapping[int, float]) -> Dist:
    """Distribution of clip(center + change, 1, 10) for a distribution over changes."""
    p = [0.0] * K
    for change, weight in delta.items():
        p[min(K, max(1, center + change)) - 1] += weight
    return normalize(p)


def rps(p: Dist, outcome: int) -> float:
    cdf, total = 0.0, 0.0
    for k in range(1, K):
        cdf += p[k - 1]
        total += (cdf - (1.0 if outcome <= k else 0.0)) ** 2
    return total / (K - 1)


def log_score(p: Dist, outcome: int) -> float:
    return -math.log(p[outcome - 1])


def skill(mean_score: float, mean_ref: float) -> float:
    return math.nan if mean_ref == 0 else 1 - mean_score / mean_ref


def block_bootstrap_skill(scores: Sequence[float], ref: Sequence[float], block: int = 7,
                          n: int = 2000, seed: int = 20261023) -> tuple[float, float, float]:
    """(point, lo95, hi95) skill of `scores` vs `ref`, paired by day."""
    s, r = np.asarray(scores, float), np.asarray(ref, float)
    point = skill(float(s.mean()), float(r.mean()))
    m = len(s)
    block = min(block, m)
    n_blocks = math.ceil(m / block)
    rng = np.random.default_rng(seed)
    sims = []
    for _ in range(n):
        starts = rng.integers(0, m - block + 1, n_blocks)
        idx = np.concatenate([np.arange(a, a + block) for a in starts])[:m]
        sims.append(skill(float(s[idx].mean()), float(r[idx].mean())))
    lo, hi = np.nanpercentile(sims, [2.5, 97.5])
    return point, float(lo), float(hi)


def calibration_bins(rows: Sequence[tuple[Dist, int]], bins: int = 5,
                     seed: int = 20261023) -> list[dict]:
    """Histogram of randomized PIT values; a calibrated forecaster fills bins evenly."""
    rng = np.random.default_rng(seed)
    counts = [0] * bins
    for p, outcome in rows:
        below = sum(p[: outcome - 1])
        u = below + float(rng.random()) * p[outcome - 1]
        counts[min(bins - 1, int(u * bins))] += 1
    return [{"lo": i / bins, "hi": (i + 1) / bins, "count": c} for i, c in enumerate(counts)]
