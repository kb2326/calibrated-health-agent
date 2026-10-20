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


def _coverage(conn, data_type: str) -> tuple[date, date] | None:
    """The contiguous [since, covered-through) range already ingested, if any."""
    row = conn.execute(
        "SELECT cursor_time FROM sync_state WHERE data_type=?", (PREFIX + data_type,)
    ).fetchone()
    if not row:
        return None
    try:
        lo, hi = (date.fromisoformat(p) for p in row[0].split(".."))
    except ValueError:
        return None
    return lo, hi


def _count(conn, data_type: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM raw_points WHERE data_type=?", (data_type,)
    ).fetchone()[0]


def _save(conn, data_type: str, lo: date, hi: date) -> None:
    conn.execute(
        """INSERT INTO sync_state (data_type, cursor_time, last_synced_at)
           VALUES (?, ?, ?)
           ON CONFLICT(data_type) DO UPDATE SET
             cursor_time=excluded.cursor_time, last_synced_at=excluded.last_synced_at""",
        (PREFIX + data_type, f"{lo.isoformat()}..{hi.isoformat()}", db.now_iso()),
    )
    conn.commit()  # rows (committed per window below) and cursor land together


def _window(conn, data_type: str, lo: date, hi: date, inserted: dict, errors: dict) -> bool:
    """Ingest [lo, hi); False (with the window rolled back) on an API failure."""
    before = _count(conn, data_type)
    counters = {"fetched": 0, "inserted": 0}
    try:
        sync.ingest(
            conn, data_type, f"{lo.isoformat()}T00:00:00+00:00",
            f"{hi.isoformat()}T00:00:00+00:00", counters, inclusive_end_day=False,
        )
    except client.HealthApiError as e:
        conn.rollback()  # drop the partial window, keep completed ones
        errors[data_type] = str(e)[:200]
        return False
    inserted[data_type] += _count(conn, data_type) - before
    return True


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
            cov = _coverage(conn, data_type)
            if cov is None or since > cov[1]:  # nothing stored, or a gap: start a fresh range
                cov = (since, since)
            known_lo, known_hi = cov
            ok = True
            # Forward: from the end of known coverage (or `since`) up to today.
            cursor = max(since, known_hi)
            while ok and cursor < end:
                window_end = min(cursor + step, end)
                ok = _window(conn, data_type, cursor, window_end, inserted, errors)
                if ok:
                    known_hi = window_end
                    _save(conn, data_type, known_lo, known_hi)
                cursor = window_end
            # Backward: extend coverage down to `since`, newest window first, so the
            # recorded range stays contiguous and never shrinks.
            while ok and since < known_lo:
                lo = max(since, known_lo - step)
                ok = _window(conn, data_type, lo, known_lo, inserted, errors)
                if ok:
                    known_lo = lo
                    _save(conn, data_type, known_lo, known_hi)
    if errors:
        raise BackfillError(inserted, errors)
    return inserted
