"""Ingestion loop.

For each tracked data type: fetch the civil-day window from `civil.sync_days` (a trailing
lookback of `civil.LOOKBACK_DAYS` days plus today, or further back after missed runs),
upsert into raw_points, rebuild that type's daily_metrics, and record the cursor. Every
value is attributed to an owner-zone civil day by the rule in `health_data.civil`.

Idempotent: unique keys plus upserts mean a refetch of unchanged data writes nothing, and
the `inserted` count reports new-or-changed rows only. Server-aggregated buckets (dailyRollUp
and the heart-rate rollUp) are upserted, so a day fetched while still in progress is
overwritten by the later, complete value instead of freezing at the first one.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import yaml
from health_core.settings import get_settings

from health_data import auth, civil, client, db, obs

log = obs.get_logger(__name__)

CONFIG = yaml.safe_load((get_settings().config_dir / "health.yaml").read_text())

INSERT_BATCH = 5000

# Insert, or update only when something actually changed: an UPDATE whose WHERE is false
# changes no row, so `total_changes` counts exactly the new-or-changed rows.
_UPSERT_SQL = """INSERT INTO raw_points
   (data_type, start_time, end_time, value, unit, source, raw_json, inserted_at, civil_date)
   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
   ON CONFLICT(data_type, start_time, end_time, source) DO UPDATE SET
     value=excluded.value, unit=excluded.unit, raw_json=excluded.raw_json,
     civil_date=excluded.civil_date
   WHERE raw_points.value IS NOT excluded.value
      OR raw_points.unit IS NOT excluded.unit
      OR raw_points.raw_json IS NOT excluded.raw_json
      OR raw_points.civil_date IS NOT excluded.civil_date"""

ROLLUP_SOURCE = "dailyRollUp"


def _point_row(data_type: str, point: dict) -> tuple:
    """Flatten one API point into the raw_points column order."""
    value, unit = client.extract_value(data_type, point)
    start_time, end_time = client.extract_time(data_type, point)
    day = civil.day_of_point(data_type, point) or civil.day_of_instant(start_time)
    return (
        data_type, start_time, end_time, value, unit,
        db.point_source(point), json.dumps(point), db.now_iso(), day,
    )


def _flush(conn, batch: list[tuple]) -> int:
    """Upsert a batch, returning how many rows were new or changed."""
    before = conn.total_changes
    conn.executemany(_UPSERT_SQL, batch)
    return conn.total_changes - before


def rebuild_daily(conn, data_type: str) -> None:
    """Rebuild a listed type's daily_metrics from raw_points, one row per civil day.

    Delete-then-insert so a day that no longer has any supporting point (e.g. after the
    civil-day rule moved its points) does not linger.
    """
    agg = CONFIG["data_types"].get(data_type, {}).get("agg", "mean")
    sql_agg = "SUM(value)" if agg == "sum" else "AVG(value)"
    conn.execute("DELETE FROM daily_metrics WHERE data_type = ?", (data_type,))
    conn.execute(
        f"""
        INSERT INTO daily_metrics (date, data_type, agg_value, n_points)
        SELECT civil_date, ?, {sql_agg}, COUNT(*)
        FROM raw_points
        WHERE data_type = ? AND value IS NOT NULL AND civil_date IS NOT NULL
        GROUP BY civil_date
        """,
        (data_type, data_type),
    )


def _upsert_rollup(conn, data_type: str, bucket: dict, windowed: bool) -> bool:
    """Store one server-aggregated daily bucket; True if it was new or changed.

    The bucket lands in raw_points (as the receipt, source 'dailyRollUp') and in
    daily_metrics (n_points = 1 bucket). Both are upserts: the value of a day still in
    progress is replaced by later fetches.
    """
    day = (client.window_rollup_day if windowed else client.rollup_day)(bucket)
    value, unit = (client.extract_window_value if windowed else client.extract_rollup_value)(
        data_type, bucket)
    if day is None or value is None:
        return False
    before = conn.total_changes
    conn.execute(_UPSERT_SQL, (data_type, day, day, value, unit, ROLLUP_SOURCE,
                               json.dumps(bucket), db.now_iso(), day))
    changed = conn.total_changes > before
    conn.execute(
        """INSERT INTO daily_metrics (date, data_type, agg_value, n_points)
           VALUES (?, ?, ?, 1)
           ON CONFLICT(date, data_type) DO UPDATE SET
             agg_value=excluded.agg_value, n_points=excluded.n_points""",
        (day, data_type, value),
    )
    return changed


def sync_devices(conn) -> int:
    """Upsert the paired-device inventory; returns how many devices were seen."""
    devices = client.list_paired_devices().get("pairedDevices", [])
    for dev in devices:
        conn.execute(
            """INSERT INTO devices (id, display_name, raw_json, fetched_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 display_name=excluded.display_name, raw_json=excluded.raw_json,
                 fetched_at=excluded.fetched_at""",
            (dev.get("name", ""), dev.get("deviceVersion") or dev.get("deviceType"),
             json.dumps(dev), db.now_iso()),
        )
    return len(devices)


def failed_types(summary: dict) -> list[str]:
    """Data types that failed; `_`-prefixed entries (devices) are informational only."""
    return sorted(t for t, s in summary.items() if "error" in s and not t.startswith("_"))


def exit_code(summary: dict) -> int:
    """0 when every data type synced, 1 when any failed (partial failure is a failure).

    The device inventory needs a scope that may not be granted yet; its failure is
    recorded in the summary but never fails the run.
    """
    return 1 if failed_types(summary) else 0


def changed_rows(summary: dict) -> int:
    """Total new-or-changed rows across data types (0 means the run wrote no data)."""
    return sum(int(s.get("inserted", 0)) for t, s in summary.items() if not t.startswith("_"))


# Types worth probing beyond whatever is already tracked.
PROBE_CANDIDATES = (
    "daily-heart-rate-variability", "daily-oxygen-saturation", "daily-respiratory-rate",
    "respiratory-rate-sleep-summary", "daily-sleep-temperature-derivations",
    "active-zone-minutes", "time-in-heart-rate-zone", "daily-vo2-max",
    "sedentary-period", "floors",
)


def probe(days: int, candidates: tuple[str, ...] | None = None) -> dict[str, int]:
    """Points (or rollup days with data) per readable type over the last `days` civil days.

    Types the API rejects are left out of the result, not reported as zero.
    """
    end = civil.today() + timedelta(days=1)
    start = end - timedelta(days=days)
    names = candidates if candidates is not None else tuple(
        dict.fromkeys([*CONFIG["data_types"], *PROBE_CANDIDATES])
    )
    out: dict[str, int] = {}
    for data_type in names:
        try:
            if data_type in client.ROLLUP_TYPES:
                out[data_type] = sum(
                    1
                    for b in client.iter_daily_rollups(data_type, start, end)
                    if client.extract_rollup_value(data_type, b)[0] is not None
                )
            elif data_type in client.WINDOW_ROLLUP_TYPES:
                out[data_type] = sum(1 for _ in client.iter_window_rollups(data_type, start, end))
            else:
                out[data_type] = sum(
                    1
                    for _ in client.iter_data_points(
                        data_type, civil.midnight(start).isoformat(), civil.midnight(end).isoformat()
                    )
                )
        except client.HealthApiError as e:
            log.warning(f"probe.{data_type} unreadable: {str(e)[:120]}")
    return out


def path_of(data_type: str) -> str:
    if data_type in client.ROLLUP_TYPES:
        return "dailyRollUp"
    if data_type in client.WINDOW_ROLLUP_TYPES:
        return "rollUp"
    return "list"


def ingest(conn, data_type: str, lo: date, hi: date, counters: dict[str, Any],
           rebuild: bool = True) -> None:
    """Fetch owner-zone civil days [lo, hi) for one type and store them.

    Shared by sync, backfill and repair. Summed types arrive as dailyRollUp buckets and
    heart-rate as 24 h rollUp buckets aligned to owner-zone midnight (never per-minute
    points); everything else is listed point by point. `counters["inserted"]` grows by
    the number of new-or-changed raw rows. Raises HealthApiError; the caller owns
    rollback and cursor handling.
    """
    kind = path_of(data_type)
    if kind != "list":
        windowed = kind == "rollUp"
        buckets = (client.iter_window_rollups if windowed else client.iter_daily_rollups)(
            data_type, lo, hi)
        for bucket in buckets:
            counters["fetched"] += 1
            if _upsert_rollup(conn, data_type, bucket, windowed):
                counters["inserted"] += 1
        return
    # Batched: 740k individual execute() calls held a write lock for minutes.
    # executemany amortises that, and the chunk boundary bounds peak memory.
    batch: list[tuple] = []
    start, end = civil.midnight(lo).isoformat(), civil.midnight(hi).isoformat()
    for point in client.iter_data_points(data_type, start, end):
        counters["fetched"] += 1
        batch.append(_point_row(data_type, point))
        if len(batch) >= INSERT_BATCH:
            counters["inserted"] += _flush(conn, batch)
            batch.clear()
    if batch:
        counters["inserted"] += _flush(conn, batch)
    if rebuild:
        rebuild_daily(conn, data_type)


class SyncInterrupted(RuntimeError):
    """run() stopped on an unexpected error; `__cause__` is that error.

    `summary` covers only the data types committed before it stopped, so a caller can
    tell whether the interrupted run wrote any data worth keeping.
    """

    def __init__(self, summary: dict[str, dict[str, Any]]):
        self.summary = summary
        super().__init__(f"sync stopped after {len(summary)} committed data types")


def run() -> dict:
    """Sync every tracked type. Auth errors propagate as-is; any other unexpected error
    becomes SyncInterrupted carrying the committed part of the summary."""
    db.init_db()
    summary: defaultdict[str, dict[str, Any]] = defaultdict(
        lambda: {"fetched": 0, "inserted": 0}
    )
    committed: list[str] = []
    try:
        _sync_all(summary, committed)
    except auth.AuthError:
        raise
    except Exception as exc:
        raise SyncInterrupted({t: dict(summary[t]) for t in committed}) from exc
    result = dict(summary)
    db.write_stage_output("ingest", civil.today().isoformat(), result)
    return result


def _sync_all(summary: defaultdict[str, dict[str, Any]], committed: list[str]) -> None:
    with db.connect() as conn:
        for data_type in CONFIG["data_types"]:
            row = conn.execute(
                "SELECT cursor_time FROM sync_state WHERE data_type=?", (data_type,)
            ).fetchone()
            lo, hi = civil.sync_days(row[0] if row else None, CONFIG["initial_backfill_days"])
            started = civil.now()
            try:
                ingest(conn, data_type, lo, hi, summary[data_type])
            except client.HealthApiError as e:
                summary[data_type]["error"] = str(e)
                conn.rollback()  # discard this type's partial work, keep prior types
                log.error(
                    f"ingest.{data_type} failed",
                    extra={"attrs": {
                        "span": "ingest.data_type", "status": "error",
                        "data_type": data_type, "window_start": lo.isoformat(),
                        "window_end": hi.isoformat(), "error": str(e)[:400],
                    }},
                )
                print(f"{data_type:30s} ERROR {e}", file=sys.stderr, flush=True)
                continue  # bounded: skip this type this run, don't spin retrying
            # The cursor records when this type last synced successfully; the next run
            # re-fetches from the earlier of its civil day and the lookback start.
            conn.execute(
                """INSERT INTO sync_state (data_type, cursor_time, last_synced_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(data_type) DO UPDATE SET
                     cursor_time=excluded.cursor_time, last_synced_at=excluded.last_synced_at""",
                (data_type, started.isoformat(), db.now_iso()),
            )
            # Commit per data type: rows and cursor land together, and an interrupt
            # keeps every type already finished.
            conn.commit()
            committed.append(data_type)
            s = summary[data_type]
            log.info(
                f"ingest.{data_type} ok",
                extra={"attrs": {
                    "span": "ingest.data_type", "status": "ok", "data_type": data_type,
                    "fetched": s["fetched"], "inserted": s["inserted"],
                    "window_start": lo.isoformat(), "window_end": hi.isoformat(),
                    "path": path_of(data_type),
                }},
            )
            print(
                f"{data_type:30s} fetched={s['fetched']:7d}  changed={s['inserted']:7d}",
                flush=True,
            )
        try:
            summary["_devices"]["fetched"] = sync_devices(conn)
            conn.commit()
        except client.HealthApiError as e:
            # Needs the settings scope; absent until re-consent. Never fatal.
            summary["_devices"]["error"] = str(e)[:200]
            conn.rollback()


if __name__ == "__main__":
    try:
        summary = run()
    except auth.AuthError as e:
        print(f"Auth error: {e}", file=sys.stderr)
        sys.exit(1)
    errs = failed_types(summary)
    print(f"done: {len(summary) - len(errs)} ok, {len(errs)} failed")
    sys.exit(exit_code(summary))
