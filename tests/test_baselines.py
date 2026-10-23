"""Robust personal baselines: median/MAD over worn days only."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from health_ledger import baselines
from ledger_fixtures import make_db, metric

D = date(2026, 10, 30)


def test_robust_baseline_ignores_one_outlier():
    baseline = baselines.robust_baseline([60.0] * 5 + [61.0] * 5 + [200.0])
    assert baseline is not None
    median, scale = baseline
    assert median == 61.0
    assert scale == pytest.approx(1.4826)  # MAD 1; the 200 does not inflate it


def test_baseline_none_below_min_n():
    assert baselines.robust_baseline([60.0] * 6) is None
    assert baselines.robust_baseline([60.0] * 7, min_n=7) is None  # MAD 0 -> no scale


def test_robust_z_sign_and_scale():
    assert baselines.robust_z(70.0, (60.0, 5.0)) == pytest.approx(2.0)
    assert baselines.robust_z(55.0, (60.0, 5.0)) == pytest.approx(-1.0)


def test_series_before_skips_unworn_days(tmp_path):
    conn = make_db(tmp_path / "t.db")
    for i in range(1, 6):
        day = D - timedelta(days=i)
        metric(conn, day, "sleep", 400 + i)
    conn.execute("UPDATE daily_metrics SET agg_value = 100 WHERE date = ?",
                 (str(D - timedelta(days=3)),))  # under 180 min: that night was not worn
    metric(conn, D, "sleep", 999)  # day itself never included
    values = baselines.series_before(conn, "sleep", D, "sleep", window=28)
    assert 100 not in values and 999 not in values
    assert sorted(values) == [401, 402, 404, 405]
