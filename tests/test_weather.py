"""Daily weather for the home location from Open-Meteo (Phase 4.5)."""
from __future__ import annotations

import pytest
from health_data import weather
from ledger_fixtures import make_db

PAYLOAD = {"daily": {
    "time": ["2026-10-29", "2026-10-30"],
    "temperature_2m_max": [33.1, 31.4], "temperature_2m_min": [23.0, 22.4],
    "temperature_2m_mean": [27.6, 26.5], "relative_humidity_2m_mean": [71, 78],
    "precipitation_sum": [0.0, 12.3], "uv_index_max": [8.1, 6.0],
    "sunrise": ["2026-10-29T06:05", "2026-10-30T06:05"],
    "sunset": ["2026-10-29T17:58", "2026-10-30T17:57"]}}


class Fake:
    def __init__(self, payload=PAYLOAD, fail=None):
        self.payload, self.fail, self.urls = payload, fail, []

    def __call__(self, url):
        self.urls.append(url)
        if self.fail:
            raise self.fail
        return self.payload


def test_parse_and_upsert_is_idempotent(tmp_path):
    conn = make_db(tmp_path / "h.db")
    fake = Fake()
    for _ in range(2):
        n = weather.sync_recent(conn, fetch=fake, place="Erode", latitude=11.341, longitude=77.7172)
    assert n == 2
    rows = conn.execute("SELECT date, temp_max_c, precipitation_mm, sunrise FROM weather_daily"
                        " ORDER BY date").fetchall()
    assert rows == [("2026-10-29", 33.1, 0.0, "2026-10-29T06:05"),
                    ("2026-10-30", 31.4, 12.3, "2026-10-30T06:05")]


def test_request_carries_only_the_settings_coordinates_and_dates(tmp_path):
    conn = make_db(tmp_path / "h.db")
    fake = Fake()
    weather.backfill(conn, "2026-10-01", "2026-10-30", fetch=fake, place="Erode",
                     latitude=11.341, longitude=77.7172)
    url = fake.urls[0]
    assert url.startswith("https://archive-api.open-meteo.com/v1/archive?")
    assert "latitude=11.341" in url and "longitude=77.7172" in url
    assert "start_date=2026-10-01" in url and "end_date=2026-10-30" in url
    assert "Asia%2FKolkata" in url


def test_weather_failure_is_soft(tmp_path):
    conn = make_db(tmp_path / "h.db")
    with pytest.raises(weather.WeatherError):
        weather.sync_recent(conn, fetch=Fake(fail=OSError("offline")), place="Erode",
                            latitude=11.341, longitude=77.7172)
    assert conn.execute("SELECT COUNT(*) FROM weather_daily").fetchone() == (0,)


def test_missing_values_stay_null(tmp_path):
    conn = make_db(tmp_path / "h.db")
    payload = {"daily": {"time": ["2026-10-30"], "temperature_2m_max": [None]}}
    weather.sync_recent(conn, fetch=Fake(payload), place="Erode", latitude=1.0, longitude=2.0)
    assert conn.execute("SELECT temp_max_c, temp_min_c FROM weather_daily").fetchone() == (None, None)


def test_forecast_for_any_coordinates(tmp_path):
    fake = Fake()
    days = weather.forecast(10.0, 76.9, days=2, fetch=fake)
    assert fake.urls[0].startswith("https://api.open-meteo.com/v1/forecast?")
    assert days[1] == {"date": "2026-10-30", "temp_min_c": 22.4, "temp_max_c": 31.4,
                       "temp_mean_c": 26.5, "humidity_mean": 78, "precipitation_mm": 12.3,
                       "uv_index_max": 6.0, "sunrise": "2026-10-30T06:05",
                       "sunset": "2026-10-30T17:57"}


def test_job_weather_step_is_soft(monkeypatch, tmp_path):
    from health_core.settings import Settings
    from health_data import db
    from jobs import sync_job

    path = tmp_path / "h.db"
    make_db(path).close()
    monkeypatch.setattr(db, "DB_PATH", path)

    def boom(*a, **k):
        raise weather.WeatherError("URLError")

    monkeypatch.setattr(weather, "sync_recent", boom)
    out = sync_job._weather(Settings())
    assert out == {"result": "skipped (weather unavailable)", "error": "URLError"}
