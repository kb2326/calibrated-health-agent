"""Open readiness score: how recovered the body looks this morning, computed in the open.

The Google Health API does not expose the device's proprietary readiness or recovery
score, so this is a transparent counterpart. For day D, each component is a robust z
against the personal baseline of the previous 28 worn days (median/MAD, at least 7 days):

- `hrv_z`: Fitbit daily HRV (RMSSD). Higher is better.
- `rhr_z`: daily resting heart rate. Lower is better, so it enters negated.
- `sleep_z`: last night's sleep minutes (sleep belongs to the day it ends), only when the
  night counts as worn (at least 180 minutes).

    score = clip(50 + 15 * mean(hrv_z, -rhr_z, sleep_z over available components), 0, 100)

At least two components are required; otherwise the score is None. 50 means "a usual
morning for me", and each 15 points is about one robust standard deviation.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from health_ledger import baselines, wear

MIN_COMPONENTS = 2

# component name -> (data_type, wear family, sign)
COMPONENTS = {
    "hrv_z": ("daily-heart-rate-variability", "overnight", 1.0),
    "rhr_z": ("daily-resting-heart-rate", "overnight", -1.0),
    "sleep_z": ("sleep", "sleep", 1.0),
}


def _value(conn: sqlite3.Connection, data_type: str, day: date) -> float | None:
    sql = "SELECT agg_value FROM daily_metrics WHERE data_type = ? AND date = ?"
    if data_type == "daily-heart-rate-variability":
        sql += " AND source = 'FITBIT'"  # never Apple SDNN
    row = conn.execute(sql, (data_type, day.isoformat())).fetchone()
    return None if row is None else float(row[0])


def score(conn: sqlite3.Connection, day: date) -> dict:
    worn = wear.worn(conn, day)
    components: dict[str, float | None] = {}
    for name, (data_type, family, _sign) in COMPONENTS.items():
        value = _value(conn, data_type, day) if worn[family] else None
        baseline = None
        if value is not None:
            baseline = baselines.robust_baseline(
                baselines.series_before(conn, data_type, day, family))
        components[name] = (None if value is None or baseline is None
                            else baselines.robust_z(value, baseline))
    signed = [COMPONENTS[n][2] * z for n, z in components.items() if z is not None]
    result = None
    if len(signed) >= MIN_COMPONENTS:
        result = min(100.0, max(0.0, 50 + 15 * sum(signed) / len(signed)))
    return {"score": result, "components": components, "n_components": len(signed)}
