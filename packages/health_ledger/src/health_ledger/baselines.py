"""Robust personal baselines: rolling median and MAD over worn days.

Mean and standard deviation let one illness week inflate the spread for a month; the
median and the median absolute deviation (scaled by 1.4826 to match a standard deviation
under normality) do not. Baselines only use days worn for the metric's family, are
indexed by calendar day (a gap is a gap, not "the previous row"), and never include the
day being judged.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date, timedelta
from statistics import median

from health_ledger import wear

MAD_SCALE = 1.4826


def robust_baseline(values: Sequence[float], min_n: int = 7) -> tuple[float, float] | None:
    """(median, scaled MAD), or None with fewer than `min_n` values or zero spread."""
    if len(values) < min_n:
        return None
    centre = median(values)
    scale = MAD_SCALE * median(abs(v - centre) for v in values)
    if scale == 0:
        return None
    return centre, scale


def robust_z(x: float, baseline: tuple[float, float]) -> float:
    centre, scale = baseline
    return (x - centre) / scale


def series_before(conn: sqlite3.Connection, data_type: str, day: date, family: str,
                  window: int = 28) -> list[float]:
    """`data_type` values on days worn for `family` in [day - window, day - 1]."""
    start, end = day - timedelta(days=window), day - timedelta(days=1)
    worn = wear.worn_days(conn, family, start, end)
    rows = conn.execute(
        "SELECT date, agg_value FROM daily_metrics WHERE data_type = ? AND date BETWEEN ? AND ?",
        (data_type, start.isoformat(), end.isoformat()),
    )
    return [value for d, value in rows if date.fromisoformat(d) in worn]
