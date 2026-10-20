"""Resumable full-history backfill, on the same ingestion path as `sync`.

History is walked oldest-first in windows no longer than the type's API range
cap. Rows and the type's backfill cursor commit together after every window,
so a failure keeps everything already fetched and a rerun carries on from the
first incomplete window. Re-ingesting a window is idempotent (unique keys).

The cursor lives in `sync_state` under `backfill:<type>`, separate from the
live-sync cursor (which sits near "now" and would otherwise make every
historical window look done). Its value is `<since>..<covered-through>`.
Backfill covers [since, today); today itself belongs to `sync`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from health_core.settings import get_settings

from health_data import client, db, sync

PREFIX = "backfill:"


class BackfillError(RuntimeError):
    """One or more types failed; completed windows are kept. `inserted` has counts."""

    def __init__(self, inserted: dict[str, int], errors: dict[str, str]):
        super().__init__(f"backfill incomplete for: {', '.join(sorted(errors))}")
        self.inserted = inserted
        self.errors = errors


def window_days(data_type: str) -> int:
    """Longest request window the API accepts for this type's ingestion path."""
    if data_type in client.ROLLUP_TYPES:
        return client.ROLLUP_MAX_DAYS.get(data_type, client.ROLLUP_DEFAULT_MAX_DAYS)
    return client.LIST_MAX_DAYS.get(data_type, client.LIST_DEFAULT_MAX_DAYS)


def _today() -> date:
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


def _resume_from(conn, data_type: str, since: date) -> date:
    row = conn.execute(
        "SELECT cursor_time FROM sync_state WHERE data_type=?", (PREFIX + data_type,)
    ).fetchone()
    if not row:
        return since
    try:
        stored_since, covered = (date.fromisoformat(p) for p in row[0].split(".."))
    except ValueError:
        return since
    if since < stored_since:  # asked for older history than before: start over (idempotent)
        return since
    return max(since, covered)


def _count(conn, data_type: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM raw_points WHERE data_type=?", (data_type,)
    ).fetchone()[0]


def backfill(since: date, types: list[str] | None = None) -> dict[str, int]:
    """Rows inserted per type for [since, today). Raises BackfillError on any failure."""
    db.init_db()
    end = _today()
    names = list(types) if types is not None else list(sync.CONFIG["data_types"])
    inserted: dict[str, int] = {}
    errors: dict[str, str] = {}
    with db.connect() as conn:
        for data_type in names:
            inserted[data_type] = 0
            step = timedelta(days=window_days(data_type))
            cursor = _resume_from(conn, data_type, since)
            while cursor < end:
                window_end = min(cursor + step, end)
                before = _count(conn, data_type)
                counters = {"fetched": 0, "inserted": 0}
                try:
                    sync.ingest(
                        conn, data_type, f"{cursor.isoformat()}T00:00:00+00:00",
                        f"{window_end.isoformat()}T00:00:00+00:00", counters,
                        inclusive_end_day=False,
                    )
                except client.HealthApiError as e:
                    conn.rollback()  # drop the partial window, keep completed ones
                    errors[data_type] = str(e)[:200]
                    break
                conn.execute(
                    """INSERT INTO sync_state (data_type, cursor_time, last_synced_at)
                       VALUES (?, ?, ?)
                       ON CONFLICT(data_type) DO UPDATE SET
                         cursor_time=excluded.cursor_time, last_synced_at=excluded.last_synced_at""",
                    (PREFIX + data_type, f"{since.isoformat()}..{window_end.isoformat()}",
                     db.now_iso()),
                )
                conn.commit()
                inserted[data_type] += _count(conn, data_type) - before
                cursor = window_end
    if errors:
        raise BackfillError(inserted, errors)
    return inserted
