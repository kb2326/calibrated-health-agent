"""Corrected associations: detrended, lagged, Benjamini–Hochberg across the whole run."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from health_ledger import associations
from ledger_fixtures import journal, make_db, metric

START = date(2026, 9, 1)


def test_bh_matches_reference():
    q = associations.benjamini_hochberg([0.01, 0.04, 0.03, 0.2])
    assert q == pytest.approx([0.04, 0.16 / 3, 0.16 / 3, 0.2])


def test_bh_empty():
    assert associations.benjamini_hochberg([]) == []


def test_associations_skip_small_n(tmp_path):
    conn = make_db(tmp_path / "t.db")
    for i in range(5):
        day = START + timedelta(days=i)
        metric(conn, day, "sleep", 400 + i)
        journal(conn, day, 5, 5 + (i % 2), 3)
    assert associations.run(conn) == []


def test_associations_find_a_planted_lag0_link(tmp_path):
    conn = make_db(tmp_path / "t.db")
    for i in range(40):
        day = START + timedelta(days=i)
        sleep = 360 + 30 * ((i * 7) % 5)  # varied, worn every night
        metric(conn, day, "sleep", sleep)
        energy = 1 + (sleep - 360) // 30 * 2  # energy tracks sleep exactly
        journal(conn, day, 5, energy, 3)
    rows = associations.run(conn, min_n=10)
    hit = next(r for r in rows if r["metric"] == "sleep" and r["target"] == "energy" and r["lag"] == 0)
    assert hit["rho"] == pytest.approx(1.0)
    assert hit["q"] < 0.05
    assert set(hit) == {"metric", "target", "lag", "rho", "n", "p", "q"}


def test_mean_diff_permutation_is_seeded_and_two_sided():
    from health_ledger.associations import mean_diff_permutation

    cond, other = [3, 3, 4, 3, 2], [6, 7, 6, 5, 7, 6]
    effect, p = mean_diff_permutation(cond, other)
    assert effect == pytest.approx(3.0 - 6.1666667, abs=1e-6)
    assert p < 0.05 and (effect, p) == mean_diff_permutation(cond, other)
    flipped = mean_diff_permutation(other, cond)
    assert flipped[0] == pytest.approx(-effect) and abs(flipped[1] - p) < 0.02
    assert mean_diff_permutation([5, 5], [5, 5])[1] == 1.0
