"""Distributions over the journal's 1..10 scale and the proper scores that grade them."""
from __future__ import annotations

import math

import pytest
from health_ledger import dist


def _onehot(k: int) -> dist.Dist:
    return tuple(1.0 if i == k - 1 else 0.0 for i in range(10))


def test_rps_perfect_is_zero():
    assert dist.rps(_onehot(7), 7) == 0.0


def test_rps_uniform_known_value():
    assert dist.rps(tuple([0.1] * 10), 5) == pytest.approx(0.85 / 9, abs=1e-4)


def test_rps_penalises_distance():
    assert dist.rps(_onehot(6), 5) < dist.rps(_onehot(9), 5)


def test_log_score():
    assert dist.log_score(tuple([0.1] * 10), 3) == pytest.approx(math.log(10))


def test_normalize_floors_and_sums_to_one():
    p = dist.normalize([1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    assert sum(p) == pytest.approx(1.0) and min(p) > 0
    assert dist.log_score(p, 10) < math.inf  # a floored zero never gives an infinite score


@pytest.mark.parametrize("bad", [[0.1] * 9, [-0.1] + [0.11] * 9, [math.nan] * 10, [0] * 10])
def test_normalize_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        dist.normalize(bad)


def test_from_counts_is_smoothed():
    p = dist.from_counts([0, 0, 0, 0, 3, 0, 0, 0, 0, 0], prior=1.0)
    assert p[4] == pytest.approx(4 / 13) and p[0] == pytest.approx(1 / 13)


def test_discretized_normal_sums_to_one_and_peaks_at_mean():
    p = dist.discretized_normal(6.0, 1.0)
    assert sum(p) == pytest.approx(1.0)
    assert max(range(10), key=lambda i: p[i]) == 5
    tail = dist.discretized_normal(12.0, 0.1)  # far above the scale folds into 10
    assert tail[9] == pytest.approx(1.0, abs=1e-3)


def test_shift_clips_to_scale():
    p = dist.shift(9, {0: 0.5, 2: 0.5})
    assert p[8] == pytest.approx(0.5, abs=1e-3) and p[9] == pytest.approx(0.5, abs=1e-3)


def test_skill_negative_when_worse():
    assert dist.skill(0.2, 0.1) == pytest.approx(-1.0)
    assert dist.skill(0.05, 0.1) == pytest.approx(0.5)
    assert math.isnan(dist.skill(0.1, 0.0))


def test_bootstrap_is_seeded():
    scores = [0.05, 0.1, 0.08, 0.12, 0.07, 0.09, 0.11, 0.06, 0.1, 0.08, 0.09, 0.07]
    ref = [0.1, 0.12, 0.1, 0.15, 0.09, 0.1, 0.14, 0.08, 0.12, 0.1, 0.11, 0.1]
    a = dist.block_bootstrap_skill(scores, ref)
    assert a == dist.block_bootstrap_skill(scores, ref)
    point, lo, hi = a
    assert lo <= point <= hi and point == pytest.approx(dist.skill(sum(scores) / 12, sum(ref) / 12))


def test_calibration_bins_count_every_row():
    rows = [(tuple([0.1] * 10), k) for k in range(1, 11)] * 3
    bins = dist.calibration_bins(rows, bins=5)
    assert [b["count"] for b in bins] and sum(b["count"] for b in bins) == 30
    assert bins[0]["lo"] == 0.0 and bins[-1]["hi"] == 1.0
