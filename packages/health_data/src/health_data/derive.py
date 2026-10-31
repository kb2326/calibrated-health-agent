"""Detail tables derived from `raw_points.raw_json` (schema v5).

The daily roll-up keeps one number per type and day, which loses most of what a person asks
about. The API's payloads already hold it, and we store every payload, so this module
rebuilds the detail from them without any API call:

- `sleep_sessions`: minutes asleep (not time in bed), deep / light / REM / awake minutes,
  time to fall asleep, efficiency, main sleep vs nap;
- `exercise_sessions`: workout type, active duration, calories, distance, steps, average
  heart rate, active zone minutes and minutes per heart-rate zone;
- `night_vitals`: skin temperature against its personal baseline, SpO2 average / low / high,
  HRV including deep sleep, non-REM heart rate, breathing rate per sleep stage;
- `activity_breakdown`: fat-burn / cardio / peak zone minutes, light / moderate / vigorous
  active minutes, time in each heart-rate zone;
- `hr_zone_thresholds`: the person's zone boundaries.

`rebuild` replaces those tables in one transaction and is safe to run on every sync. A
missing sub-field becomes NULL, never a guess. `daily_metrics` and the ledger are not touched.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterator
from typing import Any

TABLES = ("sleep_sessions", "exercise_sessions", "night_vitals", "activity_breakdown",
          "hr_zone_thresholds")


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _seconds_to_min(v: Any) -> float | None:
    if isinstance(v, str) and v.endswith("s"):
        v = v[:-1]
    s = _num(v)
    return None if s is None else round(s / 60, 2)


def _dig(node: Any, path: str) -> Any:
    for part in path.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def _rows(conn: sqlite3.Connection, data_type: str) -> Iterator[tuple[str, str, str, dict]]:
    """(civil_date, start_time, source, payload section) for every parseable point."""
    camel = "".join(w.capitalize() if i else w for i, w in enumerate(data_type.split("-")))
    for day, start, source, raw in conn.execute(
            "SELECT civil_date, start_time, COALESCE(source, ''), raw_json FROM raw_points"
            " WHERE data_type = ? ORDER BY start_time", (data_type,)):
        try:
            section = json.loads(raw).get(camel)
        except (ValueError, AttributeError):
            continue
        if isinstance(section, dict) and day:
            yield day, start, source, section


def _minutes_between(start: str | None, end: str | None) -> float | None:
    from datetime import datetime

    if not start or not end:
        return None
    try:
        t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((t1 - t0).total_seconds() / 60, 2)


def _sleep(conn: sqlite3.Connection) -> list[tuple]:
    out = []
    for day, start, source, s in _rows(conn, "sleep"):
        interval = s.get("interval") or {}
        summary = s.get("summary") or {}
        stages = {(st or {}).get("type"): _num((st or {}).get("minutes"))
                  for st in summary.get("stagesSummary") or []}
        asleep = _num(summary.get("minutesAsleep"))
        period = _num(summary.get("minutesInSleepPeriod")) or _minutes_between(
            interval.get("startTime"), interval.get("endTime"))
        main = (s.get("metadata") or {}).get("mainSleep")
        out.append((day, interval.get("startTime") or start, interval.get("endTime"),
                    None if main is None else int(bool(main)), asleep,
                    _num(summary.get("minutesAwake")), _num(summary.get("minutesToFallAsleep")),
                    period, stages.get("DEEP"), stages.get("LIGHT"), stages.get("REM"),
                    stages.get("AWAKE"), (asleep / period) if asleep and period else None, source))
    return out


def _exercise(conn: sqlite3.Connection) -> list[tuple]:
    out = []
    for day, start, source, e in _rows(conn, "exercise"):
        m = e.get("metricsSummary") or {}
        zones = m.get("heartRateZoneDurations") or {}
        distance_mm = _num(m.get("distanceMillimeters"))
        out.append((day, (e.get("interval") or {}).get("startTime") or start, e.get("exerciseType"),
                    e.get("displayName"), _seconds_to_min(e.get("activeDuration")),
                    _num(m.get("caloriesKcal")),
                    None if distance_mm is None else round(distance_mm / 1_000_000, 3),
                    _num(m.get("steps")), _num(m.get("averageHeartRateBeatsPerMinute")),
                    _num(m.get("activeZoneMinutes")), _seconds_to_min(zones.get("lightTime")),
                    _seconds_to_min(zones.get("moderateTime")),
                    _seconds_to_min(zones.get("vigorousTime")),
                    _seconds_to_min(zones.get("peakTime")), source))
    return out


def _prefer_fitbit(rows: list[tuple[str, str, str, dict]]) -> dict[str, dict]:
    """One section per day: a Fitbit source wins over others (RMSSD vs SDNN must not mix)."""
    best: dict[str, tuple[bool, dict]] = {}
    for day, _start, source, section in rows:
        fitbit = "FITBIT" in source.upper()
        if day not in best or (fitbit and not best[day][0]):
            best[day] = (fitbit, section)
    return {day: section for day, (_, section) in best.items()}


def _night(conn: sqlite3.Connection) -> list[tuple]:
    temp = _prefer_fitbit(list(_rows(conn, "daily-sleep-temperature-derivations")))
    spo2 = _prefer_fitbit(list(_rows(conn, "daily-oxygen-saturation")))
    hrv = _prefer_fitbit(list(_rows(conn, "daily-heart-rate-variability")))
    resp = _prefer_fitbit(list(_rows(conn, "respiratory-rate-sleep-summary")))
    out = []
    for day in sorted(set(temp) | set(spo2) | set(hrv) | set(resp)):
        t, o, h, r = temp.get(day, {}), spo2.get(day, {}), hrv.get(day, {}), resp.get(day, {})
        nightly, base = _num(t.get("nightlyTemperatureCelsius")), _num(t.get("baselineTemperatureCelsius"))
        out.append((day, nightly, base,
                    None if nightly is None or base is None else nightly - base,
                    _num(o.get("averagePercentage")), _num(o.get("lowerBoundPercentage")),
                    _num(o.get("upperBoundPercentage")),
                    _num(h.get("averageHeartRateVariabilityMilliseconds")),
                    _num(h.get("deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds")),
                    _num(h.get("nonRemHeartRateBeatsPerMinute")),
                    _num(_dig(r, "fullSleepStats.breathsPerMinute")),
                    _num(_dig(r, "deepSleepStats.breathsPerMinute")),
                    _num(_dig(r, "lightSleepStats.breathsPerMinute")),
                    _num(_dig(r, "remSleepStats.breathsPerMinute"))))
    return out


def _activity(conn: sqlite3.Connection) -> list[tuple]:
    days: dict[str, dict[str, float | None]] = defaultdict(dict)
    for day, _s, _src, a in _rows(conn, "active-zone-minutes"):
        days[day].update(fat_burn_azm=_num(a.get("sumInFatBurnHeartZone")),
                         cardio_azm=_num(a.get("sumInCardioHeartZone")),
                         peak_azm=_num(a.get("sumInPeakHeartZone")))
    for day, _s, _src, a in _rows(conn, "active-minutes"):
        for entry in a.get("activeMinutesRollupByActivityLevel") or []:
            level = str((entry or {}).get("activityLevel", "")).lower()
            if level in ("light", "moderate", "vigorous"):
                days[day][f"{level}_active_min"] = _num((entry or {}).get("activeMinutesSum"))
    for day, _s, _src, z in _rows(conn, "time-in-heart-rate-zone"):
        for entry in z.get("timeInHeartRateZones") or []:
            zone = str((entry or {}).get("heartRateZone", "")).lower()
            if zone in ("light", "moderate", "vigorous", "peak"):
                days[day][f"zone_{zone}_min"] = _seconds_to_min((entry or {}).get("duration"))
    cols = ("fat_burn_azm", "cardio_azm", "peak_azm", "light_active_min", "moderate_active_min",
            "vigorous_active_min", "zone_light_min", "zone_moderate_min", "zone_vigorous_min",
            "zone_peak_min")
    return [(day, *(v.get(c) for c in cols)) for day, v in sorted(days.items())]


def _zones(conn: sqlite3.Connection) -> list[tuple]:
    out = {}
    for day, _s, _src, z in _rows(conn, "daily-heart-rate-zones"):
        for entry in z.get("heartRateZones") or []:
            zone = (entry or {}).get("heartRateZoneType")
            if zone:
                out[(day, zone)] = (day, zone, _num(entry.get("minBeatsPerMinute")),
                                    _num(entry.get("maxBeatsPerMinute")))
    return list(out.values())


_INSERT = {
    "sleep_sessions": "INSERT OR REPLACE INTO sleep_sessions VALUES (" + ",".join("?" * 14) + ")",
    "exercise_sessions": "INSERT OR REPLACE INTO exercise_sessions VALUES (" + ",".join("?" * 15) + ")",
    "night_vitals": "INSERT OR REPLACE INTO night_vitals VALUES (" + ",".join("?" * 14) + ")",
    "activity_breakdown": "INSERT OR REPLACE INTO activity_breakdown VALUES (" + ",".join("?" * 11) + ")",
    "hr_zone_thresholds": "INSERT OR REPLACE INTO hr_zone_thresholds VALUES (?,?,?,?)",
}
_BUILD = {"sleep_sessions": _sleep, "exercise_sessions": _exercise, "night_vitals": _night,
          "activity_breakdown": _activity, "hr_zone_thresholds": _zones}


def rebuild(conn: sqlite3.Connection) -> dict[str, int]:
    """Replace every detail table from raw_points in one transaction; rows per table."""
    built = {table: _BUILD[table](conn) for table in TABLES}
    with conn:
        for table in TABLES:
            conn.execute(f"DELETE FROM {table}")
            conn.executemany(_INSERT[table], built[table])
    return {table: len(rows) for table, rows in built.items()}
