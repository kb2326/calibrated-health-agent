"""Read-only Google Health API client, built on the official discovery client.

The API publishes a discovery document (147 schemas, 27 methods, revision
20260817), so `googleapiclient.discovery.build` generates correctly-shaped
methods for every endpoint instead of us hand-writing REST calls.

That surface includes writes — dataPoints.create/patch/batchDelete,
users.updateProfile/updateSettings. Since a generated client can reach all of
them, the read-only guarantee is enforced here by an explicit allowlist:
`_read` refuses to dispatch any method not named in READ_METHODS. The two
POSTs on the list are rollups, which compute over existing data and create
nothing — read-only is a property of the operation, not the HTTP verb.
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import date, datetime, timedelta

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from health_data.auth import get_credentials

MAX_RETRIES = 3

# Every method this project is permitted to call. Anything absent — every
# create, patch, and delete the API offers — is unreachable by construction.
READ_METHODS = {
    "getProfile",
    "getSettings",
    "getIdentity",
    "getIrnProfile",
    "pairedDevices.list",
    "pairedDevices.get",
    "dataPoints.list",
    "dataPoints.get",
    "dataPoints.reconcile",
    "dataPoints.rollUp",
    "dataPoints.dailyRollUp",
    "dataPoints.exportExerciseTcx",
}


class HealthApiError(RuntimeError):
    pass


_service = None


def service():
    """The discovery-built service, created once per process."""
    global _service
    if _service is None:
        _service = build(
            "health",
            "v4",
            credentials=get_credentials(),
            cache_discovery=False,
            static_discovery=False,
        )
    return _service


def _read(method_name: str, request):
    """Execute a request, refusing anything outside the read allowlist.

    The identity is taken from the request itself via `methodId` (which the
    generated client stamps as e.g. "health.users.dataTypes.dataPoints.list"),
    not from the caller's label. Checking the label alone would let
    _read("dataPoints.list", points_api.create(...)) sail through the gate —
    the guard has to bind to the thing it is guarding.
    """
    actual = getattr(request, "methodId", None)
    if actual is None:
        raise HealthApiError(
            f"refusing to execute a request with no methodId (labelled {method_name!r}). "
            "Only requests built by the discovery client may be dispatched."
        )
    short = actual.removeprefix("health.").removeprefix("users.").removeprefix("dataTypes.")
    if short not in READ_METHODS:
        raise HealthApiError(
            f"refusing to call {actual}: not in the read-only allowlist. "
            "This client has no code path that can create, update, or delete "
            "health data."
        )
    if short != method_name:
        raise HealthApiError(
            f"label/request mismatch: caller declared {method_name!r} but the "
            f"request is {actual!r}. Refusing to dispatch."
        )
    for attempt in range(MAX_RETRIES):
        try:
            return request.execute()
        except HttpError as e:
            status = e.resp.status
            if status == 429 or status >= 500:
                time.sleep(2**attempt)
                continue
            raise HealthApiError(f"{status}: {e}") from None
    raise HealthApiError(f"{method_name} failed after {MAX_RETRIES} retries")


# --- Filter construction -----------------------------------------------
#
# dataPoints.list takes a single AIP-160 `filter` expression; the field to
# filter on differs per data type:
#
#   sample   -> <name>.sample_time.physical_time   compared as a UTC instant
#   daily    -> <name>.date                        compared as a bare date
#   interval -> <name>.interval.civil_start_time   compared as civil (zone-less)
TIME_FIELD = {
    "steps": "interval",
    "active-minutes": "interval",
    "distance": "interval",
    "total-calories": "interval",
    "exercise": "interval",
    "sleep": "interval",
    "heart-rate": "sample",
    "daily-resting-heart-rate": "daily",
    "heart-rate-variability": "sample",
    "oxygen-saturation": "sample",
    "weight": "sample",
    # Daily summaries filter on <name>.date; the discovery doc's filter help
    # gives `daily_heart_rate_variability.date` as the canonical example.
    "daily-heart-rate-variability": "daily",
    "daily-oxygen-saturation": "daily",
    "daily-respiratory-rate": "daily",
    "daily-sleep-temperature-derivations": "daily",
    "daily-vo2-max": "daily",
    # One sample per night, stamped with sampleTime.
    "respiratory-rate-sleep-summary": "sample",
    # Interval types (the default); listed so the table is the full inventory.
    "floors": "interval",
    "active-zone-minutes": "interval",
    "sedentary-period": "interval",
    "time-in-heart-rate-zone": "interval",
}

# Types whose filter path isn't derivable from the rule above.
FILTER_FIELD_OVERRIDE = {
    # sleep only supports filtering on when the session ended
    "sleep": "sleep.interval.civil_end_time",
}

# The API rejects a larger pageSize for these two.
SMALL_PAGE_CAP = {"exercise", "sleep"}


def filter_path(data_type: str) -> str:
    if data_type in FILTER_FIELD_OVERRIDE:
        return FILTER_FIELD_OVERRIDE[data_type]
    kind = TIME_FIELD.get(data_type, "interval")
    name = data_type.replace("-", "_")
    if kind == "sample":
        return f"{name}.sample_time.physical_time"
    if kind == "daily":
        return f"{name}.date"
    return f"{name}.interval.civil_start_time"


def _has_timezone(ts: str) -> bool:
    if ts.endswith("Z"):
        return True
    tail = ts.partition("T")[2]
    return "+" in tail or "-" in tail


def _as_utc(ts: str) -> str:
    """RFC3339 with an explicit zone, as physical-time fields expect."""
    return ts if _has_timezone(ts) else ts + "Z"


def _as_civil(ts: str) -> str:
    """Zone-less local datetime — civil fields reject a timezone designator."""
    ts = ts.split("+")[0].split("Z")[0]
    if "T" in ts:
        day, _, clock = ts.partition("T")
        ts = f"{day}T{clock.split('-')[0]}"
    return ts[:19]


def build_filter(data_type: str, start_time: str, end_time: str) -> str:
    """Compose the `filter` expression for one type's time window.

    The API supports only >= and < (never <= or >), so the window is
    half-open, which also keeps consecutive syncs from double-counting.
    """
    path = filter_path(data_type)
    kind = (
        "override"
        if data_type in FILTER_FIELD_OVERRIDE
        else TIME_FIELD.get(data_type, "interval")
    )
    if kind == "sample":
        lo, hi = _as_utc(start_time), _as_utc(end_time)
    elif kind == "daily":
        lo, hi = start_time[:10], end_time[:10]
    else:  # interval and override are both civil-time comparisons
        lo, hi = _as_civil(start_time), _as_civil(end_time)
    return f'{path} >= "{lo}" AND {path} < "{hi}"'


# --- Listing ------------------------------------------------------------

MAX_PAGES = 1000
MAX_EMPTY_PAGES = 5


def _parent(data_type: str) -> str:
    return f"users/me/dataTypes/{data_type}"


# Documented maximum query range per data type. Exceeding it is not always
# rejected — a 30-day heart-rate request returned data without complaint —
# so requests are chunked rather than trusted to fail loudly.
LIST_MAX_DAYS = {
    "heart-rate": 14,
    "active-minutes": 14,
    "total-calories": 14,
    "calories-in-heart-rate-zone": 14,
}
LIST_DEFAULT_MAX_DAYS = 90


def iter_data_points(
    data_type: str,
    start_time: str,
    end_time: str,
    max_pages: int = MAX_PAGES,
) -> Iterator[dict]:
    """Yields raw DataPoint dicts for one type across every window and page.

    The window is split to respect the per-type query-range cap before
    pagination begins, so a 30-day backfill of a capped type becomes three
    compliant requests instead of one silently-truncated one.
    """
    span = LIST_MAX_DAYS.get(data_type, LIST_DEFAULT_MAX_DAYS)
    lo = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    hi = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
    if lo >= hi:
        return
    # Daily-summary types compare bare dates, so a window that opens and
    # closes within the same calendar day collapses to `date >= "X" AND
    # date < "X"` — an empty range the API rejects outright. Re-running a
    # sync on the day one already ran is normal, so treat it as "nothing
    # new" rather than an error.
    if TIME_FIELD.get(data_type) == "daily" and lo.date() >= hi.date():
        return
    cursor = lo
    while cursor < hi:
        chunk_end = min(cursor + timedelta(days=span), hi)
        yield from _iter_window(
            data_type, cursor.isoformat(), chunk_end.isoformat(), max_pages
        )
        cursor = chunk_end


def _iter_window(
    data_type: str,
    start_time: str,
    end_time: str,
    max_pages: int = MAX_PAGES,
) -> Iterator[dict]:
    """Yields raw DataPoint dicts for one compliant window across all pages.

    This API keeps handing back a nextPageToken after a window is exhausted —
    a token is not a promise of more data — so pagination stops on either an
    empty token or MAX_EMPTY_PAGES consecutive empty pages, with max_pages as
    the outer backstop.
    """
    points_api = service().users().dataTypes().dataPoints()
    request = points_api.list(
        parent=_parent(data_type),
        filter=build_filter(data_type, start_time, end_time),
        pageSize=25 if data_type in SMALL_PAGE_CAP else 1000,
    )
    empty_streak = 0
    for _ in range(max_pages):
        if request is None:
            return
        response = _read("dataPoints.list", request)
        points = response.get("dataPoints", [])
        yield from points
        empty_streak = 0 if points else empty_streak + 1
        if empty_streak >= MAX_EMPTY_PAGES:
            return
        if not response.get("nextPageToken"):
            return
        request = points_api.list_next(request, response)


# --- Daily rollups ------------------------------------------------------
#
# Counted totals are not served by list — it returns zero points for them.
# dailyRollUp pre-aggregates per civil day, which is also more correct than
# summing raw points ourselves since the server owns day-boundary semantics.
ROLLUP_TYPES = {
    "steps", "distance", "total-calories", "active-minutes",
    # floors rejects `list` outright (reconcile/rollup/dailyRollup only); the
    # other three are minute-granular streams, stored as one bucket per day.
    "floors", "active-zone-minutes", "sedentary-period", "time-in-heart-rate-zone",
}

# The API rejects a rollup range longer than this, per type (surfaced in its
# own INVALID_ROLLUP_QUERY_DURATION error metadata). Chunk requests to fit.
ROLLUP_MAX_DAYS = {
    "calories-in-heart-rate-zone": 14,
    "heart-rate": 14,
    "active-minutes": 14,
    "total-calories": 14,
}
ROLLUP_DEFAULT_MAX_DAYS = 90


def _civil(d: date) -> dict:
    return {"date": {"year": d.year, "month": d.month, "day": d.day}}


def iter_daily_rollups(data_type: str, start: date, end: date) -> Iterator[dict]:
    """Yields one pre-aggregated bucket per civil day in [start, end)."""
    points_api = service().users().dataTypes().dataPoints()
    max_days = ROLLUP_MAX_DAYS.get(data_type, ROLLUP_DEFAULT_MAX_DAYS)
    window_start = start
    while window_start < end:
        window_end = min(window_start + timedelta(days=max_days), end)
        response = _read(
            "dataPoints.dailyRollUp",
            points_api.dailyRollUp(
                parent=_parent(data_type),
                body={
                    "range": {"start": _civil(window_start), "end": _civil(window_end)},
                    # documented as optional, but the live API 400s without it
                    "windowSizeDays": 1,
                },
            ),
        )
        yield from response.get("rollupDataPoints", response.get("dataPoints", []))
        window_start = window_end


# Types fetched as server-side windowed aggregates instead of raw samples.
# heart-rate is the case that matters: a month of raw samples is ~740,000
# rows and several minutes of syncing, versus 30 rows here carrying avg,
# min, and max — strictly more information for daily analysis, at 0.004% of
# the storage. Not every sample type supports it (SpO2 and HRV both 400).
WINDOW_ROLLUP_TYPES = {"heart-rate"}


def iter_window_rollups(data_type: str, start: date, end: date) -> Iterator[dict]:
    """Yields one server-aggregated bucket per day via dataPoints.rollUp.

    Unlike dailyRollUp this takes a physical-time interval and an explicit
    windowSize, so it works for sample types that have no civil-day concept.
    """
    points_api = service().users().dataTypes().dataPoints()
    max_days = LIST_MAX_DAYS.get(data_type, LIST_DEFAULT_MAX_DAYS)
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=max_days), end)
        response = _read(
            "dataPoints.rollUp",
            points_api.rollUp(
                parent=_parent(data_type),
                body={
                    "range": {
                        "startTime": f"{cursor.isoformat()}T00:00:00Z",
                        "endTime": f"{chunk_end.isoformat()}T00:00:00Z",
                    },
                    "windowSize": "86400s",
                },
            ),
        )
        yield from response.get("rollupDataPoints", response.get("dataPoints", []))
        cursor = chunk_end


def window_rollup_day(bucket: dict) -> str | None:
    """The civil date a windowed rollup bucket covers, as YYYY-MM-DD."""
    for key in ("startTime", "physicalTimeInterval", "interval"):
        v = bucket.get(key)
        if isinstance(v, str):
            return v[:10]
        if isinstance(v, dict) and isinstance(v.get("startTime"), str):
            return v["startTime"][:10]
    civil = (bucket.get("civilStartTime") or {}).get("date") or {}
    if civil.get("year"):
        return f"{civil['year']:04d}-{civil['month']:02d}-{civil['day']:02d}"
    return None


def extract_window_value(data_type: str, bucket: dict) -> tuple[float | None, str | None]:
    """The representative scalar from a windowed rollup bucket."""
    section = _section(data_type, bucket)
    if not isinstance(section, dict):
        return None, None
    for key, unit in (
        ("beatsPerMinuteAvg", "bpm"),
        ("percentageAvg", "percent"),
        ("valueAvg", "value"),
    ):
        raw = _num(section.get(key))
        if raw is not None and raw > 0:
            return raw, unit
    return None, None


def rollup_day(bucket: dict) -> str | None:
    """The civil date a rollup bucket covers, as YYYY-MM-DD."""
    d = (bucket.get("civilStartTime") or {}).get("date") or {}
    if not d:
        return None
    return f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}"


def extract_rollup_value(data_type: str, bucket: dict) -> tuple[float | None, str | None]:
    """Pull the scalar total out of a rollup bucket.

    Shapes seen live: {"steps": {"countSum": "1197"}},
    {"distance": {"millimetersSum": "864963"}},
    {"totalCalories": {"kcalSum": 1131.99}}, and active-minutes, which nests a
    per-activity-level breakdown summed here into one daily figure.
    """
    section = _section(data_type, bucket)
    if not isinstance(section, dict):
        return None, None
    for key, unit in (
        ("countSum", "count"),
        ("millimetersSum", "mm"),
        ("kcalSum", "kcal"),
        ("minutesSum", "minutes"),
        ("metersSum", "m"),
    ):
        if key in section:
            try:
                return float(section[key]), unit
            except (TypeError, ValueError):
                return None, None
    # Duration-valued rollups: "28920s" strings, stored as minutes.
    if "durationSum" in section:
        secs = _seconds(section["durationSum"])
        return (None, None) if secs is None else (round(secs / 60, 2), "minutes")
    zones = section.get("timeInHeartRateZones")
    if isinstance(zones, list):
        parts = [_seconds((z or {}).get("duration")) for z in zones]
        known = [p for p in parts if p is not None]
        return (round(sum(known) / 60, 2), "minutes") if known else (None, None)
    zone_sums = [
        _num(section.get(k))
        for k in ("sumInFatBurnHeartZone", "sumInCardioHeartZone", "sumInPeakHeartZone")
    ]
    if any(v is not None for v in zone_sums):
        return sum(v for v in zone_sums if v is not None), "minutes"
    for value in section.values():  # active-minutes: sum the per-level breakdown
        if isinstance(value, list):
            total, found = 0.0, False
            for entry in value:
                for k, v in (entry or {}).items():
                    if k.endswith("Sum") or k == "activeMinutes":
                        try:
                            total += float(v)
                            found = True
                        except (TypeError, ValueError):
                            pass
            if found:
                return total, "minutes"
    return None, None


def _seconds(v) -> float | None:
    """A protobuf Duration string such as "3600s" -> 3600.0."""
    if isinstance(v, str) and v.endswith("s"):
        v = v[:-1]
    return _num(v)


def _section(data_type: str, point: dict) -> dict:
    camel = "".join(w.capitalize() if i else w for i, w in enumerate(data_type.split("-")))
    return point.get(camel) or point.get(data_type) or {}


def extract_time(data_type: str, point: dict) -> tuple[str, str]:
    """(start, end) ISO timestamps for a listed point.

    v4 nests the timestamp inside the type-specific section, and the shape
    depends on the type's time field — there is no top-level startTime:

        sample   -> {"heartRate": {"sampleTime": {"physicalTime": "...Z"}}}
        interval -> {"sleep": {"interval": {"startTime": ..., "endTime": ...}}}
        daily    -> {"dailyRestingHeartRate": {"date": {"year": ...}}}

    Reading the wrong one yields "" for every point, which silently collapses
    a whole sync into one row via the raw_points UNIQUE constraint.
    """
    section = _section(data_type, point)
    if not isinstance(section, dict):
        return "", ""
    interval = section.get("interval") or {}
    if interval.get("startTime"):
        return interval["startTime"], interval.get("endTime", interval["startTime"])
    sample = section.get("sampleTime") or {}
    if sample.get("physicalTime"):
        return sample["physicalTime"], sample["physicalTime"]
    d = section.get("date") or {}
    if d.get("year"):
        day = f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}"
        return day, day
    return "", ""


# The scalar each listed type contributes to daily_metrics, and the unit it
# lands in. Note the API serialises int64 fields as JSON *strings* (protobuf
# convention), so "125" is a perfectly normal heart rate — never test these
# with isinstance(v, (int, float)).
VALUE_FIELD: dict[str, tuple[str, str, float]] = {
    # data type: (payload field, stored unit, multiplier)
    "heart-rate": ("beatsPerMinute", "bpm", 1),
    "daily-resting-heart-rate": ("beatsPerMinute", "bpm", 1),
    "oxygen-saturation": ("percentage", "percent", 1),
    "heart-rate-variability": (
        "rootMeanSquareOfSuccessiveDifferencesMilliseconds",
        "ms",
        1,
    ),
    "weight": ("weightGrams", "kg", 0.001),
    # Dotted paths descend into nested messages.
    "daily-heart-rate-variability": ("averageHeartRateVariabilityMilliseconds", "ms", 1),
    "daily-oxygen-saturation": ("averagePercentage", "percent", 1),
    "daily-respiratory-rate": ("breathsPerMinute", "breaths/min", 1),
    "daily-sleep-temperature-derivations": ("nightlyTemperatureCelsius", "celsius", 1),
    "daily-vo2-max": ("vo2Max", "ml/kg/min", 1),
    "respiratory-rate-sleep-summary": ("fullSleepStats.breathsPerMinute", "breaths/min", 1),
}

# Types with no scalar of their own — the meaningful daily figure is how long
# they lasted, which we derive from the interval.
DURATION_TYPES = {"sleep", "exercise"}


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _duration_minutes(section: dict) -> float | None:
    from datetime import datetime

    interval = section.get("interval") or {}
    start, end = interval.get("startTime"), interval.get("endTime")
    if not start or not end:
        return None
    try:
        t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((t1 - t0).total_seconds() / 60, 2)


def extract_value(data_type: str, point: dict) -> tuple[float | None, str | None]:
    """The scalar this point contributes, plus its unit."""
    section = _section(data_type, point)
    if not isinstance(section, dict):
        return None, None
    if data_type in DURATION_TYPES:
        return _duration_minutes(section), "minutes"
    spec = VALUE_FIELD.get(data_type)
    if spec:
        field, unit, mult = spec
        node: object = section
        for part in field.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        raw = _num(node)
        # A zero is not a reading for any of these — no one has a heart rate,
        # SpO2, HRV, or mass of zero. It means the source did not populate
        # this particular field. That happens because the API reconciles
        # several platforms: Apple HealthKit reports HRV as SDNN and leaves
        # RMSSD at 0, so eight HealthKit points were dragging a whole day's
        # mean to 0.0 and firing a false alert.
        if raw is None or raw <= 0:
            return None, None
        return raw * mult, unit
    # Unknown type: take the sole numeric-ish field if there is exactly one.
    numeric = {k: _num(v) for k, v in section.items() if _num(v) is not None}
    if len(numeric) == 1:
        k, v = next(iter(numeric.items()))
        return v, k
    return None, None


# --- Profile / device reads --------------------------------------------


def get_profile() -> dict:
    return _read("getProfile", service().users().getProfile(name="users/me/profile"))


def get_user_settings() -> dict:
    return _read("getSettings", service().users().getSettings(name="users/me/settings"))


def list_paired_devices() -> dict:
    return _read(
        "pairedDevices.list",
        service().users().pairedDevices().list(parent="users/me"),
    )
