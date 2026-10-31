"""Daily weather from Open-Meteo (free, no key; attribution: open-meteo.com, CC BY 4.0).

History comes from the archive API and recent days and the forecast from the forecast API.
Only coordinates and dates leave the machine. The coordinates come from settings (the home
location) or, in the web front end, from the device the owner is holding. The model never
picks them, so this outbound call can't carry health data.

A failure raises `WeatherError`. The sync job logs it and carries on: weather is context,
never a reason to fail a run.
"""
from __future__ import annotations

import json
import sqlite3
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from health_data import db

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"
TIMEZONE = "Asia/Kolkata"
DAILY = ("temperature_2m_max", "temperature_2m_min", "temperature_2m_mean",
         "relative_humidity_2m_mean", "precipitation_sum", "uv_index_max", "sunrise", "sunset")
FIELDS = {"temperature_2m_min": "temp_min_c", "temperature_2m_max": "temp_max_c",
          "temperature_2m_mean": "temp_mean_c", "relative_humidity_2m_mean": "humidity_mean",
          "precipitation_sum": "precipitation_mm", "uv_index_max": "uv_index_max",
          "sunrise": "sunrise", "sunset": "sunset"}
TIMEOUT_S = 15

Fetch = Callable[[str], dict]


class WeatherError(RuntimeError):
    """Open-Meteo could not be reached or returned something unusable."""


def _http_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:  # noqa: S310 (fixed https host)
        return json.load(resp)


def _url(base: str, latitude: float, longitude: float, **extra: Any) -> str:
    query = {"latitude": round(float(latitude), 4), "longitude": round(float(longitude), 4),
             "daily": ",".join(DAILY), "timezone": TIMEZONE, **extra}
    return f"{base}?{urllib.parse.urlencode(query)}"


def _days(payload: dict) -> list[dict]:
    daily = payload.get("daily") if isinstance(payload, dict) else None
    if not isinstance(daily, dict) or not isinstance(daily.get("time"), list):
        raise WeatherError("unexpected Open-Meteo response")
    out = []
    for i, day in enumerate(daily["time"]):
        row = {"date": day}
        for api, col in FIELDS.items():
            values = daily.get(api)
            row[col] = values[i] if isinstance(values, list) and i < len(values) else None
        out.append(row)
    return out


def _get(url: str, fetch: Fetch | None) -> list[dict]:
    try:
        return _days((fetch or _http_json)(url))
    except WeatherError:
        raise
    except Exception as exc:  # network, HTTP, JSON: one soft error type
        raise WeatherError(type(exc).__name__) from exc


def _upsert(conn: sqlite3.Connection, days: list[dict], *, place: str, latitude: float,
            longitude: float, source: str) -> int:
    stamp = db.utc_stamp()
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO weather_daily (date, place, latitude, longitude, temp_min_c,"
            " temp_max_c, temp_mean_c, humidity_mean, precipitation_mm, uv_index_max, sunrise,"
            " sunset, source, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(d["date"], place, latitude, longitude, d["temp_min_c"], d["temp_max_c"],
              d["temp_mean_c"], d["humidity_mean"], d["precipitation_mm"], d["uv_index_max"],
              d["sunrise"], d["sunset"], source, stamp) for d in days])
    return len(days)


def sync_recent(conn: sqlite3.Connection, *, place: str, latitude: float, longitude: float,
                fetch: Fetch | None = None) -> int:
    """The last 7 days and today for the home location (forecast API, past_days)."""
    days = _get(_url(FORECAST, latitude, longitude, past_days=7, forecast_days=1), fetch)
    return _upsert(conn, days, place=place, latitude=latitude, longitude=longitude,
                   source="open-meteo-forecast")


def backfill(conn: sqlite3.Connection, start: str, end: str, *, place: str, latitude: float,
             longitude: float, fetch: Fetch | None = None) -> int:
    """History for [start, end] from the archive API (about a five-day lag)."""
    days = _get(_url(ARCHIVE, latitude, longitude, start_date=start, end_date=end), fetch)
    return _upsert(conn, days, place=place, latitude=latitude, longitude=longitude,
                   source="open-meteo-archive")


def forecast(latitude: float, longitude: float, *, days: int = 7, past_days: int = 0,
             fetch: Fetch | None = None) -> list[dict]:
    """Daily forecast (and optionally recent days) for any coordinates; nothing stored."""
    return _get(_url(FORECAST, latitude, longitude, forecast_days=max(1, min(days, 16)),
                     past_days=max(0, min(past_days, 92))), fetch)
