"""Wear rules: whether the watch was worn on a civil day, per metric family.

A day that was not worn is a gap, never a low value: it is excluded from baselines,
features and forecasts' inputs, and reported as missing. The rules, per family:

| Family      | Worn on day D when                                                        |
|-------------|---------------------------------------------------------------------------|
| `sleep`     | the `sleep` daily value is at least 180 minutes                           |
| `overnight` | a `daily-resting-heart-rate` value, or a FITBIT `daily-heart-rate-variability` value, exists for D |
| `day`       | a `daily-resting-heart-rate` value exists for D, or `steps` is at least 1000 |

Resting heart rate is only computed by the device when it was worn for much of the day,
which is why it counts for both `overnight` and `day`. Apple HRV (SDNN) does not count
toward `overnight`: features read Fitbit RMSSD only.
"""
from __future__ import annotations

import sqlite3
from datetime import date

FAMILIES = ("sleep", "overnight", "day")

MIN_SLEEP_MINUTES = 180
MIN_STEPS = 1000

# One SQL predicate per family over daily_metrics rows of a single day `d.date`.
_RULES = {
    "sleep": f"EXISTS (SELECT 1 FROM daily_metrics m WHERE m.date = d.date "
             f"AND m.data_type = 'sleep' AND m.agg_value >= {MIN_SLEEP_MINUTES})",
    "overnight": "EXISTS (SELECT 1 FROM daily_metrics m WHERE m.date = d.date "
                 "AND (m.data_type = 'daily-resting-heart-rate' "
                 "OR (m.data_type = 'daily-heart-rate-variability' AND m.source = 'FITBIT')))",
    "day": f"EXISTS (SELECT 1 FROM daily_metrics m WHERE m.date = d.date "
           f"AND (m.data_type = 'daily-resting-heart-rate' "
           f"OR (m.data_type = 'steps' AND m.agg_value >= {MIN_STEPS})))",
}


def worn(conn: sqlite3.Connection, day: date) -> dict[str, bool]:
    """Worn or not worn on `day`, for every family."""
    return {family: bool(conn.execute(
        f"SELECT {_RULES[family]} FROM (SELECT ? AS date) d", (day.isoformat(),)
    ).fetchone()[0]) for family in FAMILIES}


def worn_days(conn: sqlite3.Connection, family: str, start: date, end: date) -> set[date]:
    """Days in [start, end] (inclusive) that were worn for `family`."""
    rows = conn.execute(
        f"""SELECT d.date FROM (SELECT DISTINCT date FROM daily_metrics
                                WHERE date BETWEEN ? AND ?) d
            WHERE {_RULES[family]}""",
        (start.isoformat(), end.isoformat()),
    )
    return {date.fromisoformat(r[0]) for r in rows}
