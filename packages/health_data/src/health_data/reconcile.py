"""Reconciled (multi-source-merged) reads, used for parity checks and wear inputs.

`dataPoints.reconcile` (GET v4/{+parent}/dataPoints:reconcile; discovery
revision 20261016) merges every data source into one stream and leaves out
intervals the device was not worn. Request fields: `parent`
(users/me/dataTypes/<type>), `filter` (same AIP-160 grammar as list),
`pageSize` (default 1440, max 10000; 25 for sleep/exercise), `pageToken`, and
`dataSourceFamily` (default all-sources). Response: `dataPoints[]`
(ReconciledDataPoint, one type-specific section per point, same shape as a
list point) and `nextPageToken`. Not every type supports it - total-calories
answers 400 "Reconcile is not supported ... rollup, dailyRollup" - and floors
supports reconcile/rollup/dailyRollup but not list.

The fine-grained points are never stored point-by-point in SQLite. The stored
daily value comes from `dailyRollUp`; reconcile is only the independent
re-derivation that `parity_report` compares it against.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

from health_data import client

# Counted totals: stored as the server's dailyRollUp, never as raw points.
SUMMED_TYPES = frozenset(
    {"steps", "distance", "total-calories", "active-minutes", "floors", "active-zone-minutes"}
)

# Types the API refuses to reconcile (so there is nothing to compare against).
RECONCILE_UNSUPPORTED = frozenset({"total-calories"})

RECONCILE_PAGE_SIZE = 10000
PARITY_TOLERANCE = 0.02


def _midnight(d: date) -> str:
    return f"{d.isoformat()}T00:00:00"


def iter_reconciled(data_type: str, start: date, end: date) -> Iterator[dict]:
    """Yield merged data points for civil days in [start, end), across all pages."""
    points_api = client.service().users().dataTypes().dataPoints()
    span = client.LIST_MAX_DAYS.get(data_type, client.LIST_DEFAULT_MAX_DAYS)
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=span), end)
        request = points_api.reconcile(
            parent=client._parent(data_type),
            filter=client.build_filter(data_type, _midnight(cursor), _midnight(chunk_end)),
            pageSize=25 if data_type in client.SMALL_PAGE_CAP else RECONCILE_PAGE_SIZE,
        )
        for _ in range(client.MAX_PAGES):
            if request is None:
                break
            response = client._read("dataPoints.reconcile", request)
            yield from response.get("dataPoints", [])
            if not response.get("nextPageToken"):
                break
            request = points_api.reconcile_next(request, response)
        cursor = chunk_end


def daily_summed(data_type: str, start: date, end: date) -> dict[date, float]:
    """The stored daily value per civil day, from dailyRollUp."""
    out: dict[date, float] = {}
    for bucket in client.iter_daily_rollups(data_type, start, end):
        day = client.rollup_day(bucket)
        value, _ = client.extract_rollup_value(data_type, bucket)
        if day is not None and value is not None:
            out[date.fromisoformat(day)] = value
    return out


def _point_day(data_type: str, point: dict) -> date | None:
    section = client._section(data_type, point)
    civil = ((section.get("interval") or {}).get("civilStartTime") or {}).get("date") or {}
    if civil.get("year"):
        return date(civil["year"], civil["month"], civil["day"])
    start, _ = client.extract_time(data_type, point)
    return date.fromisoformat(start[:10]) if start else None


def _point_amount(data_type: str, point: dict) -> float | None:
    """One reconciled point's contribution, in the unit its rollup uses."""
    section = client._section(data_type, point)
    if data_type == "steps":
        return client._num(section.get("count"))
    if data_type == "floors":
        return client._num(section.get("count"))
    if data_type == "distance":
        return client._num(section.get("millimeters"))
    if data_type == "active-zone-minutes":
        return client._num(section.get("activeZoneMinutes"))
    if data_type == "active-minutes":
        levels = section.get("activeMinutesByActivityLevel") or []
        vals = [client._num((lv or {}).get("activeMinutes")) for lv in levels]
        known = [v for v in vals if v is not None]
        return sum(known) if known else None
    return None


def parity_report(
    data_type: str, start: date, end: date
) -> list[tuple[date, float, float]]:
    """(day, dailyRollUp value, sum of reconciled points) for each day with either.

    Empty for types the API cannot reconcile.
    """
    if data_type in RECONCILE_UNSUPPORTED:
        return []
    rolled = daily_summed(data_type, start, end)
    summed: dict[date, float] = {}
    for point in iter_reconciled(data_type, start, end):
        day, amount = _point_day(data_type, point), _point_amount(data_type, point)
        if day is not None and amount is not None:
            summed[day] = summed.get(day, 0.0) + amount
    return [(d, rolled.get(d, 0.0), summed.get(d, 0.0)) for d in sorted(rolled.keys() | summed.keys())]


def parity_summary(
    rows: list[tuple[date, float, float]], tolerance: float = PARITY_TOLERANCE
) -> tuple[int, int]:
    """(days in agreement, worn days) - a worn day is one where reconcile has data."""
    worn = [(r, s) for _, r, s in rows if s > 0]
    agree = sum(1 for r, s in worn if abs(r - s) <= tolerance * max(r, s))
    return agree, len(worn)
