"""Forecasting results page: DM-HLN, reliability bands, honest small-n output, aggregates only."""
from __future__ import annotations

import json
import math
import re
from datetime import date, timedelta

import pytest
from health_ledger import chain, dist, report
from health_ledger.forecasters import gemini
from ledger_fixtures import make_db

G = gemini.FORECASTER_ID
START = date(2026, 9, 1)


def test_dm_hln_known_value():
    # d = [1, 2, 4]: mean 7/3, gamma0 = 14/9, DM = sqrt(10.5), HLN factor sqrt(2/3) -> sqrt(7);
    # Student t with 2 df has a closed form: two-sided p = 1 - t / sqrt(2 + t^2)
    stat, p = report.dm_hln([1.0, 2.0, 4.0])
    assert stat == pytest.approx(math.sqrt(7), rel=1e-9)
    assert p == pytest.approx(1 - math.sqrt(7) / 3, rel=1e-6)
    neg, p_neg = report.dm_hln([-1.0, -2.0, -4.0])
    assert neg == pytest.approx(-stat) and p_neg == pytest.approx(p)
    zero, p_zero = report.dm_hln([0.0, 0.0, 0.0, 0.0])
    assert (zero, p_zero) == (0.0, 1.0)
    big, p_big = report.dm_hln([0.5 + 0.01 * (i % 3) for i in range(30)])
    assert big > 10 and p_big < 1e-6


def test_student_t_matches_normal_for_large_df():
    assert report.t_sf(1.96, 10_000) == pytest.approx(0.025, abs=2e-4)
    assert report.t_sf(0.0, 5) == pytest.approx(0.5)


def test_reliability_counts_sum_to_n():
    p = dist.discretized_normal(6, 1.5)
    pairs = [(p, y) for y in [4, 5, 5, 6, 6, 6, 7, 7, 8, 9] * 3]
    bins = report.reliability(pairs)
    assert len(bins) == 5 and sum(b["count"] for b in bins) == 30
    for b in bins:
        assert b["band_lo"] <= 6 <= b["band_hi"]  # 30 / 5 expected per bin under calibration
    assert report.reliability(pairs) == bins  # seeded
    assert sum(b["count"] for b in report.reliability([])) == 0


def _scored_day(conn, day: date, outcomes: dict[str, int], bets: dict) -> None:
    d = day.isoformat()
    conn.execute("INSERT INTO snapshots VALUES (?, '{}', 'h', 't', '[]')", (d,))
    for name, p in bets.items():
        for target, y in outcomes.items():
            conn.execute("INSERT INTO forecasts (day, forecaster, target, probs_json, abstain_reason, "
                         "locked_at) VALUES (?, ?, ?, ?, NULL, 't')", (d, name, target, json.dumps(p)))
            conn.execute("INSERT INTO scores (day, forecaster, target, outcome, rps, log_score, "
                         "scored_at) VALUES (?, ?, ?, ?, ?, ?, 't')",
                         (d, name, target, y, dist.rps(p, y), dist.log_score(p, y)))
    chain.append(conn, d, "outcome", {"x": d})


@pytest.fixture
def conn(tmp_path):
    c = make_db(tmp_path / "t.db")
    chain.ensure_plan_hash(c, "ab")
    yield c
    c.close()


def _fill(conn, days: int):
    sharp, flat = dist.discretized_normal(7, 1), tuple([0.1] * 10)
    for i in range(days):
        y = 7 if i % 3 else 6
        _scored_day(conn, START + timedelta(days=i), {"mood": 6, "energy": y, "soreness": 2},
                    {G: sharp, "persistence": flat, "climatology": flat})


def test_below_ten_days_says_not_yet(conn):
    _fill(conn, 6)
    rep = report.build(conn)
    assert rep["primary"]["n"] == 6 and rep["primary"]["dm"] is None
    md = report.render(rep)
    assert "not yet" in md and "n = 6" in md


def test_ten_days_reports_skill_and_dm(conn):
    _fill(conn, 14)
    rep = report.build(conn)
    primary = rep["primary"]
    assert primary["n"] == 14 and primary["skill_vs_persistence"][0] > 0
    stat, p = primary["dm"]
    assert stat < 0 and 0 <= p <= 1  # Gemini's RPS is lower (better) than persistence's
    sharp = {(s["id"], s["target"]): s["sd"] for s in rep["sharpness"]}
    assert sharp[(G, "energy")] < sharp[("persistence", "energy")]
    md = report.render(rep)
    assert "<svg" in md and "n = 14" in md and "not yet" not in md.split("## Primary")[1].split("##")[0]


def test_report_contains_no_dates_or_daily_values(conn):
    _fill(conn, 14)
    md = report.render(report.build(conn))
    assert not re.search(r"\b20\d\d-\d\d-\d\d\b", md)
    # every number is an aggregate rounded like the public board (at most 2 decimals)
    assert not re.search(r"\d\.\d{3,}", md.split("<svg")[0])
    assert not re.search(r"\d\.\d{3,}", md)  # SVG coordinates are integers too
    daily = dist.rps(dist.discretized_normal(7, 1), 6)
    assert f"{daily:.4f}" not in md


def test_rows_below_ten_days_show_no_numbers(conn):
    _fill(conn, 3)  # with n this small a "mean" is close to a daily value
    md = report.render(report.build(conn))
    table = md.split("## Every forecaster")[1].split("## Calibration")[0]
    assert "not yet" in table and "n = 3" in table
    assert not re.search(r"\d\.\d\d", table)
