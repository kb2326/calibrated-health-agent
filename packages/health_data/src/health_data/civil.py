"""The civil-day rule: which owner-zone day every stored daily value belongs to.

This module is the single place the rule is defined. Every daily value belongs to one
civil day in the owner's time zone (`Settings.timezone`, Asia/Kolkata), never to a UTC
date. Per data type:

| Family (examples)                                   | Belongs to                                               |
|-----------------------------------------------------|----------------------------------------------------------|
| dailyRollUp totals (steps, distance, total-calories, active-minutes, floors, active-zone-minutes, sedentary-period, time-in-heart-rate-zone) | The bucket's server civil day (the request range is owner-zone civil dates) |
| heart-rate (dataPoints.rollUp, 24 h windows)         | The owner-zone day of the window start; windows are requested from owner-zone midnight, so a bucket is exactly one owner day |
| Daily summaries (`*.date`: daily-resting-heart-rate, daily-heart-rate-variability, daily-oxygen-saturation, daily-respiratory-rate, daily-sleep-temperature-derivations, daily-vo2-max) | The `date` field as the API gives it |
| sleep                                                | The owner-zone day the session **ends** on (last night's sleep belongs to the morning of D) |
| Other interval types (exercise)                      | The owner-zone day the interval starts on                |
| Samples (heart-rate-variability, oxygen-saturation, weight, respiratory-rate-sleep-summary) | The owner-zone day of the sample's physical time (the nightly respiratory summary is stamped at wake-up, so it lands on the morning of D) |
| Journal                                              | The date the owner enters (the evening of D)              |

Physical times without a zone designator are read as UTC. Travel is not modelled: a value
recorded abroad still lands on the owner-zone day.

Request windows are computed in the owner zone and converted per filter kind: physical-time
filters (samples, rollUp) get the UTC instant of owner-zone midnight; civil-time filters
(intervals, sleep end) get the zone-less owner-zone wall clock; date filters get the
owner-zone date. A sync window always includes today, so the Phase 2 lock can see last
night's sleep, HRV and resting heart rate on the morning of D.

Every sync re-fetches a trailing lookback of `LOOKBACK_DAYS` civil days per type. Late
uploads (sleep summaries posted after waking, a watch that syncs a day late) are picked up on
the next run; storage is idempotent (unique keys plus upserts), so refetching is safe.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from health_core.settings import get_settings

# Civil days before today that every sync re-fetches (in addition to today).
LOOKBACK_DAYS = 3


def zone() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def now() -> datetime:
    """The current instant (UTC). Tests replace this to freeze time."""
    return datetime.now(UTC)


def today() -> date:
    """Today's civil date in the owner zone."""
    return now().astimezone(zone()).date()


def midnight(day: date) -> datetime:
    """Owner-zone midnight that starts `day`, as an aware datetime."""
    return datetime.combine(day, time(0), tzinfo=zone())


def parse_instant(ts: str) -> datetime | None:
    """A physical timestamp as an aware datetime; a zone-less one is read as UTC."""
    if not ts:
        return None
    try:
        moment = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def day_of_instant(ts: str) -> str | None:
    """The owner-zone civil date (YYYY-MM-DD) of a physical timestamp."""
    moment = parse_instant(ts)
    return None if moment is None else moment.astimezone(zone()).date().isoformat()


def _ymd(d: dict) -> str | None:
    if not d.get("year"):
        return None
    return f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}"


def _section(data_type: str, point: dict) -> dict:
    camel = "".join(w.capitalize() if i else w for i, w in enumerate(data_type.split("-")))
    section = point.get(camel) or point.get(data_type) or {}
    return section if isinstance(section, dict) else {}


def day_of_point(data_type: str, point: dict) -> str | None:
    """The civil day a listed data point belongs to, per the table in this docstring."""
    section = _section(data_type, point)
    interval = section.get("interval") or {}
    if interval.get("startTime"):
        if data_type == "sleep":
            return day_of_instant(interval.get("endTime") or interval["startTime"])
        return day_of_instant(interval["startTime"])
    sample = section.get("sampleTime") or {}
    if sample.get("physicalTime"):
        return day_of_instant(sample["physicalTime"])
    return _ymd(section.get("date") or {})


def day_of_window_bucket(bucket: dict) -> str | None:
    """The civil day a dataPoints.rollUp bucket covers (owner-zone day of its start)."""
    for key in ("startTime", "physicalTimeInterval", "interval"):
        v = bucket.get(key)
        if isinstance(v, str):
            return day_of_instant(v)
        if isinstance(v, dict) and isinstance(v.get("startTime"), str):
            return day_of_instant(v["startTime"])
    return _ymd((bucket.get("civilStartTime") or {}).get("date") or {})


def sync_days(cursor_time: str | None, initial_days: int) -> tuple[date, date]:
    """The civil-day window [lo, hi) one sync fetches for a type.

    hi is tomorrow (today included). lo is the earlier of the lookback start and the day
    of the previous run's cursor, so a gap of several missed runs is still covered; a type
    never synced starts `initial_days` back.
    """
    t = today()
    hi = t + timedelta(days=1)
    lookback = t - timedelta(days=LOOKBACK_DAYS)
    if cursor_time is None:
        return t - timedelta(days=initial_days), hi
    cursor_day = day_of_instant(cursor_time)
    if cursor_day is None:
        return lookback, hi
    return min(lookback, date.fromisoformat(cursor_day)), hi
