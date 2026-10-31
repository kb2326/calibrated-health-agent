"""Small-sample statistics for eval results, standard library and numpy only.

- `wilson`: a pass rate's 95% interval that behaves at 0% and 100% (unlike the normal one).
- `mcnemar_exact`: are two variants different on the *same* cases? Exact binomial test on the
  discordant pairs (b = only A passed, c = only B passed).
- `paired_bootstrap_diff`: the size of that difference with a seeded percentile interval.
- `pass_hat_k`: pass^k, the share of cases that pass on every one of k trials (reliability,
  not best-of-k).
- `min_detectable_diff`: the smallest paired difference a suite of n cases can see, so a
  "no difference" result is reported with what it could and could not have detected.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

SEED = 20261030


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def paired_bootstrap_diff(a: list[bool], b: list[bool], n: int = 2000,
                          seed: int = SEED) -> tuple[float, float, float]:
    """Mean(a) - mean(b) over paired cases, with a 95% percentile interval."""
    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    if not a:
        return 0.0, 0.0, 0.0
    diff = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    rng = np.random.default_rng(seed)
    means = diff[rng.integers(0, len(diff), size=(n, len(diff)))].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(diff.mean()), float(lo), float(hi)


def pass_hat_k(trials: list[list[bool]]) -> float:
    if not trials:
        return 0.0
    return sum(all(t) for t in trials) / len(trials)


def min_detectable_diff(n: int, p: float = 0.8, alpha: float = 0.05,
                        power: float = 0.8) -> float:
    """Normal approximation: (z_{1-α/2} + z_power) · sqrt(2p(1-p)/n)."""
    z = NormalDist().inv_cdf
    return (z(1 - alpha / 2) + z(power)) * math.sqrt(2 * p * (1 - p) / n)
