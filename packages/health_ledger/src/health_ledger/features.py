"""The feature snapshot for day D: the exact inputs every forecaster sees at the lock.

No leakage: a forecast for D may use data through the end of the sleep that ended on the
morning of D. So overnight values (sleep, HRV, resting HR, readiness) are D's own, while
daytime totals (steps) and the journal stop at D - 1. Values from days that were not
worn are None, and every None input is named in `missing` so a deadline lock records
what it lacked. The snapshot is serialised canonically and hashed; that hash goes into
the ledger, so anyone can check that each forecaster got the same inputs.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, timedelta

from health_ledger import readiness, wear

TARGETS = ("mood", "energy", "soreness")
OPTIONAL = ("sleep_minutes", "hrv_rmssd", "resting_hr", "readiness", "steps_prev_day",
            "journal_prev_day")


def canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _metric(conn: sqlite3.Connection, data_type: str, day: date, *, source: str | None = None
            ) -> float | None:
    sql, args = "SELECT agg_value FROM daily_metrics WHERE data_type = ? AND date = ?", [
        data_type, day.isoformat()]
    if source is not None:
        sql += " AND source = ?"
        args.append(source)
    row = conn.execute(sql, args).fetchone()
    return None if row is None else float(row[0])


def _outcomes_before(conn: sqlite3.Connection, day: date) -> dict[date, dict[str, int]]:
    rows = conn.execute(
        "SELECT date, mood, energy, soreness FROM journal_outcome WHERE date < ? ORDER BY date",
        (day.isoformat(),))
    return {date.fromisoformat(d): dict(zip(TARGETS, vals, strict=True))
            for d, *vals in rows}


def snapshot(conn: sqlite3.Connection, day: date) -> tuple[dict, list[str]]:
    worn_today = wear.worn(conn, day)
    prev = day - timedelta(days=1)
    worn_prev = wear.worn(conn, prev)
    outcomes = _outcomes_before(conn, day)
    last7 = [outcomes[d] for d in sorted(outcomes) if d >= day - timedelta(days=7)]
    snap = {
        "day": day.isoformat(),
        "weekday": day.weekday(),
        "sleep_minutes": _metric(conn, "sleep", day) if worn_today["sleep"] else None,
        "hrv_rmssd": (_metric(conn, "daily-heart-rate-variability", day, source="FITBIT")
                      if worn_today["overnight"] else None),
        "resting_hr": (_metric(conn, "daily-resting-heart-rate", day)
                       if worn_today["overnight"] else None),
        "readiness": readiness.score(conn, day)["score"],
        "steps_prev_day": _metric(conn, "steps", prev) if worn_prev["day"] else None,
        "journal_prev_day": outcomes.get(prev),
        "journal_last7": {t: [o[t] for o in last7] for t in TARGETS},
        "journal_days_total": len(outcomes),
    }
    missing = [k for k in OPTIONAL if snap[k] is None]
    return snap, missing
