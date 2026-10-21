"""Re-fetch history and recompute daily_metrics under the civil-day rule (`health_data.civil`).

Used once after the switch from mixed UTC/owner-zone attribution, and safe to rerun. For
each type, over [first stored day (or today - days), today]:

- dailyRollUp / rollUp types: the type's server-aggregated rows in the range are deleted
  and fetched again, so heart-rate buckets are re-cut at owner-zone midnight and any day
  frozen at a partial value is replaced.
- listed types: every point in the range is fetched again (upsert on the stable platform
  source key: recovers points that arrived after their window had passed without
  duplicating stored ones), every stored row's civil_date is recomputed, and the type's
  daily_metrics are rebuilt.

Each type commits on its own; an API failure rolls that type back and leaves it as it was.
The report holds counts and day ranges only, never values.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from health_data import backfill, civil, client, db, sync


def _summary(conn, data_type: str) -> dict[str, Any]:
    days, first, last = conn.execute(
        "SELECT COUNT(*), MIN(date), MAX(date) FROM daily_metrics WHERE data_type=?",
        (data_type,),
    ).fetchone()
    raw = conn.execute(
        "SELECT COUNT(*) FROM raw_points WHERE data_type=?", (data_type,)
    ).fetchone()[0]
    return {"days": days, "first": first, "last": last, "raw_rows": raw}


def _first_day(conn, data_type: str) -> date | None:
    """Earliest day this type has any stored history or backfill coverage for."""
    candidates: list[str] = []
    for sql in ("SELECT MIN(date) FROM daily_metrics WHERE data_type=?",
                "SELECT MIN(civil_date) FROM raw_points WHERE data_type=?"):
        value = conn.execute(sql, (data_type,)).fetchone()[0]
        if value:
            candidates.append(value[:10])
    cov = backfill._coverage(conn, data_type)
    if cov is not None:
        candidates.append(cov[0].isoformat())
    return date.fromisoformat(min(candidates)) if candidates else None


def repair(days: int | None = None, types: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Repair each type; returns {type: {before, after, window, fetched, changed} | {error}}."""
    db.init_db()
    today = civil.today()
    hi = today + timedelta(days=1)
    names = list(types) if types else list(sync.CONFIG["data_types"])
    report: dict[str, dict[str, Any]] = {}
    with db.connect() as conn:
        for data_type in names:
            before = _summary(conn, data_type)
            if days is not None:
                lo = today - timedelta(days=days)
            else:
                lo = _first_day(conn, data_type) or today - timedelta(
                    days=sync.CONFIG["initial_backfill_days"])
            counters = {"fetched": 0, "inserted": 0}
            kind = sync.path_of(data_type)
            try:
                if kind != "list":
                    conn.execute(
                        "DELETE FROM raw_points WHERE data_type=? AND source=? "
                        "AND civil_date >= ? AND civil_date < ?",
                        (data_type, sync.ROLLUP_SOURCE, lo.isoformat(), hi.isoformat()),
                    )
                    conn.execute(
                        "DELETE FROM daily_metrics WHERE data_type=? AND date >= ? AND date < ?",
                        (data_type, lo.isoformat(), hi.isoformat()),
                    )
                step = timedelta(days=backfill.window_days(data_type))
                cursor = lo
                while cursor < hi:
                    end = min(cursor + step, hi)
                    sync.ingest(conn, data_type, cursor, end, counters, rebuild=False)
                    cursor = end
                if kind == "list":
                    db.fill_civil_dates(conn, data_type)
                    sync.rebuild_daily(conn, data_type)
                conn.commit()
            except client.HealthApiError as exc:
                conn.rollback()
                report[data_type] = {"error": str(exc)[:200], "before": before}
                continue
            report[data_type] = {
                "before": before, "after": _summary(conn, data_type),
                "window": f"{lo.isoformat()}..{hi.isoformat()}",
                "fetched": counters["fetched"], "changed": counters["inserted"],
            }
    return report
