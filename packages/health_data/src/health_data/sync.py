"""Ingestion loop — Phase 2, loop #1.

For each tracked data type: fetch everything since the last cursor, upsert
into raw_points (idempotent via UNIQUE constraint), roll up into
daily_metrics, advance the cursor. Safe to re-run: a second run with no new
data upserts zero rows and reports that explicitly.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import yaml
from health_core.settings import get_settings

from health_data import auth, client, db, obs

log = obs.get_logger(__name__)

CONFIG = yaml.safe_load((get_settings().config_dir / "health.yaml").read_text())


def _window_for(data_type: str, conn) -> tuple[str, str]:
    now = datetime.now(UTC)
    row = conn.execute(
        "SELECT cursor_time FROM sync_state WHERE data_type=?", (data_type,)
    ).fetchone()
    if row:
        start = row[0]
    else:
        start = (now - timedelta(days=CONFIG["initial_backfill_days"])).isoformat()
    return start, now.isoformat()


INSERT_BATCH = 5000

_INSERT_SQL = """INSERT OR IGNORE INTO raw_points
   (data_type, start_time, end_time, value, unit, source, raw_json, inserted_at)
   VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""


def _point_row(data_type: str, point: dict) -> tuple:
    """Flatten one API point into the raw_points column order."""
    import json

    value, unit = client.extract_value(data_type, point)
    start_time, end_time = client.extract_time(data_type, point)
    ds = point.get("dataSource") or {}
    source = (ds.get("device") or {}).get("displayName") or ds.get("platform") or "unknown"
    return (
        data_type, start_time, end_time, value, unit,
        str(source), json.dumps(point), db.now_iso(),
    )


def _flush(conn, batch: list[tuple]) -> int:
    """Insert a batch, returning how many rows were genuinely new."""
    before = conn.total_changes
    conn.executemany(_INSERT_SQL, batch)
    return conn.total_changes - before


def _upsert_point(conn, data_type: str, point: dict) -> bool:
    import json

    value, unit = client.extract_value(data_type, point)
    start_time, end_time = client.extract_time(data_type, point)
    ds = point.get("dataSource") or {}
    source = (ds.get("device") or {}).get("displayName") or ds.get("platform") or "unknown"
    cur = conn.execute(
        """INSERT OR IGNORE INTO raw_points
           (data_type, start_time, end_time, value, unit, source, raw_json, inserted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data_type,
            start_time,
            end_time,
            value,
            unit,
            str(source),
            json.dumps(point),
            db.now_iso(),
        ),
    )
    return cur.rowcount > 0


def _rollup_daily(conn, data_type: str) -> None:
    agg = CONFIG["data_types"][data_type]["agg"]
    sql_agg = "SUM(value)" if agg == "sum" else "AVG(value)"
    conn.execute(
        f"""
        INSERT INTO daily_metrics (date, data_type, agg_value, n_points)
        SELECT substr(start_time, 1, 10) AS day, ?, {sql_agg}, COUNT(*)
        FROM raw_points WHERE data_type = ? AND value IS NOT NULL
        GROUP BY day
        ON CONFLICT(date, data_type) DO UPDATE SET
          agg_value=excluded.agg_value, n_points=excluded.n_points
        """,
        (data_type, data_type),
    )


def _upsert_rollup(conn, data_type: str, bucket: dict, day_of=None, value_of=None) -> bool:
    """Store one server-aggregated daily bucket straight into daily_metrics.

    These types never populate raw_points — the API only exposes them
    pre-aggregated — so n_points records the bucket count (1), not a sample
    count, and _rollup_daily is skipped for them.
    """
    import json

    day = (day_of or client.rollup_day)(bucket)
    value, unit = (value_of or client.extract_rollup_value)(data_type, bucket)
    if day is None or value is None:
        return False
    conn.execute(
        """INSERT INTO daily_metrics (date, data_type, agg_value, n_points)
           VALUES (?, ?, ?, 1)
           ON CONFLICT(date, data_type) DO UPDATE SET
             agg_value=excluded.agg_value, n_points=excluded.n_points""",
        (day, data_type, value),
    )
    conn.execute(
        """INSERT OR IGNORE INTO raw_points
           (data_type, start_time, end_time, value, unit, source, raw_json, inserted_at)
           VALUES (?, ?, ?, ?, ?, 'dailyRollUp', ?, ?)""",
        (data_type, day, day, value, unit, json.dumps(bucket), db.now_iso()),
    )
    return True


def sync_devices(conn) -> int:
    """Upsert the paired-device inventory; returns how many devices were seen."""
    import json

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


def exit_code(summary: dict) -> int:
    """0 when every type synced, 1 when any failed (partial failure is a failure)."""
    return 1 if any("error" in s for s in summary.values()) else 0


# Types worth probing beyond whatever is already tracked.
PROBE_CANDIDATES = (
    "daily-heart-rate-variability", "daily-oxygen-saturation", "daily-respiratory-rate",
    "respiratory-rate-sleep-summary", "daily-sleep-temperature-derivations",
    "active-zone-minutes", "time-in-heart-rate-zone", "daily-vo2-max",
    "sedentary-period", "floors",
)


def probe(days: int, candidates: tuple[str, ...] | None = None) -> dict[str, int]:
    """Points (or rollup days with data) per readable type over the last `days`.

    Types the API rejects are left out of the result, not reported as zero.
    """
    end = datetime.now(UTC).date()
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
                        data_type, f"{start.isoformat()}T00:00:00Z", f"{end.isoformat()}T00:00:00Z"
                    )
                )
        except client.HealthApiError as e:
            log.warning(f"probe.{data_type} unreadable: {str(e)[:120]}")
    return out


def run() -> dict:
    db.init_db()
    summary: defaultdict[str, dict[str, Any]] = defaultdict(
        lambda: {"fetched": 0, "inserted": 0}
    )
    with db.connect() as conn:
        for data_type in CONFIG["data_types"]:
            start, end = _window_for(data_type, conn)
            try:
                if data_type in client.ROLLUP_TYPES:
                    lo = datetime.fromisoformat(start).date()
                    hi = datetime.fromisoformat(end).date() + timedelta(days=1)
                    for bucket in client.iter_daily_rollups(data_type, lo, hi):
                        summary[data_type]["fetched"] += 1
                        if _upsert_rollup(conn, data_type, bucket):
                            summary[data_type]["inserted"] += 1
                elif data_type in client.WINDOW_ROLLUP_TYPES:
                    lo = datetime.fromisoformat(start).date()
                    hi = datetime.fromisoformat(end).date() + timedelta(days=1)
                    for bucket in client.iter_window_rollups(data_type, lo, hi):
                        summary[data_type]["fetched"] += 1
                        if _upsert_rollup(
                            conn, data_type, bucket,
                            day_of=client.window_rollup_day,
                            value_of=client.extract_window_value,
                        ):
                            summary[data_type]["inserted"] += 1
                else:
                    # Batched: 740k individual execute() calls held a write
                    # lock for minutes. executemany amortises that, and the
                    # chunk boundary keeps peak memory bounded on a backfill.
                    batch = []
                    for point in client.iter_data_points(data_type, start, end):
                        summary[data_type]["fetched"] += 1
                        batch.append(_point_row(data_type, point))
                        if len(batch) >= INSERT_BATCH:
                            summary[data_type]["inserted"] += _flush(conn, batch)
                            batch.clear()
                    if batch:
                        summary[data_type]["inserted"] += _flush(conn, batch)
            except client.HealthApiError as e:
                summary[data_type]["error"] = str(e)
                conn.rollback()  # discard this type's partial work, keep prior types
                log.error(
                    f"ingest.{data_type} failed",
                    extra={"attrs": {
                        "span": "ingest.data_type", "status": "error",
                        "data_type": data_type, "window_start": start, "window_end": end,
                        "error": str(e)[:400],
                    }},
                )
                print(f"{data_type:30s} ERROR {e}", file=sys.stderr, flush=True)
                continue  # bounded: skip this type this run, don't spin retrying
            if data_type not in client.ROLLUP_TYPES:
                _rollup_daily(conn, data_type)
            conn.execute(
                """INSERT INTO sync_state (data_type, cursor_time, last_synced_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(data_type) DO UPDATE SET
                     cursor_time=excluded.cursor_time, last_synced_at=excluded.last_synced_at""",
                (data_type, end, db.now_iso()),
            )
            # Commit per data type, not once at the end: a 30-day backfill of a
            # high-frequency type takes minutes, and an interrupt partway
            # through should keep everything already ingested. The cursor
            # advances in the same transaction as the rows it covers, so a
            # resumed run picks up exactly where this one stopped.
            conn.commit()
            s = summary[data_type]
            log.info(
                f"ingest.{data_type} ok",
                extra={"attrs": {
                    "span": "ingest.data_type", "status": "ok", "data_type": data_type,
                    "fetched": s["fetched"], "inserted": s["inserted"],
                    "path": ("dailyRollUp" if data_type in client.ROLLUP_TYPES
                             else "rollUp" if data_type in client.WINDOW_ROLLUP_TYPES
                             else "list"),
                }},
            )
            print(
                f"{data_type:30s} fetched={s['fetched']:7d}  inserted={s['inserted']:7d}",
                flush=True,
            )
        try:
            summary["_devices"]["fetched"] = sync_devices(conn)
            conn.commit()
        except client.HealthApiError as e:
            # Needs the settings scope; absent until re-consent. Never fatal.
            summary["_devices"]["error"] = str(e)[:200]
            conn.rollback()
    result = dict(summary)
    db.write_stage_output("ingest", datetime.now(UTC).date().isoformat(), result)
    return result


if __name__ == "__main__":
    try:
        summary = run()
    except auth.AuthError as e:
        print(f"Auth error: {e}", file=sys.stderr)
        sys.exit(1)
    errs = [d for d, s in summary.items() if "error" in s]
    print(f"done: {len(summary) - len(errs)} ok, {len(errs)} failed")
    sys.exit(exit_code(summary))
