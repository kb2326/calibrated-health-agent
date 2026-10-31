"""Phase 4.5 agent tools: data catalog, query_metric, weather; v5 tables readable, ledger blind."""
from __future__ import annotations

import inspect
import json
import sqlite3
from types import SimpleNamespace

import pytest
from health_agents import sqlguard, tools
from health_data import weather
from ledger_fixtures import make_db


def _seed(conn: sqlite3.Connection) -> None:
    for d, v in (("2026-10-28", 61.0), ("2026-10-29", 63.0), ("2026-10-30", 62.0)):
        conn.execute("INSERT OR REPLACE INTO daily_metrics (date, data_type, agg_value, n_points, source)"
                     " VALUES (?, 'daily-resting-heart-rate', ?, 1, 'FITBIT')", (d, v))
    conn.execute("DELETE FROM sleep_sessions WHERE date IN ('2026-10-29', '2026-10-30')")
    conn.execute("DELETE FROM weather_daily WHERE date = '2026-10-30'")
    for d, asleep, deep in (("2026-10-29", 400, 60), ("2026-10-30", 430, 75)):
        conn.execute("INSERT INTO sleep_sessions (date, start, main_sleep, minutes_asleep, deep_min,"
                     " source) VALUES (?, ?, 1, ?, ?, '')", (d, d + "T00:00", asleep, deep))
    conn.execute("INSERT INTO sleep_sessions (date, start, main_sleep, minutes_asleep, source)"
                 " VALUES ('2026-10-30', 'nap', 0, 30, '')")
    conn.execute("INSERT INTO weather_daily (date, place, latitude, longitude, temp_max_c, source,"
                 " fetched_at) VALUES ('2026-10-30', 'Erode', 11.3, 77.7, 31.4, 'x', 't')")
    conn.commit()


@pytest.fixture
def v5(tmp_path, monkeypatch):
    from health_eval import runner

    with runner.eval_fixture(tmp_path / "w") as (path, _):
        conn = sqlite3.connect(path)
        _seed(conn)
        conn.close()
        yield path


def test_catalog_lists_detail_tables_and_coverage(v5):
    cat = tools.data_catalog()
    metrics = {m["name"]: m for m in cat["metrics"]}
    assert "daily-resting-heart-rate" in metrics and metrics["daily-resting-heart-rate"]["unit"] == "bpm"
    tables = {t["table"]: t for t in cat["tables"]}
    assert tables["sleep_sessions"]["rows"] >= 3
    assert "minutes_asleep" in tables["sleep_sessions"]["columns"]
    assert "weather_daily" in tables
    assert cat["hint"]


def test_catalog_on_v4_database(tmp_path, monkeypatch):
    from health_data import db

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(db.SCHEMA)
    for m in db.MIGRATIONS[:4]:
        m(conn)
    conn.execute("PRAGMA user_version = 4")
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(tools, "_ro_connect", lambda: sqlite3.connect(f"file:{path}?mode=ro", uri=True))
    cat = tools.data_catalog()
    assert all(t["table"] != "sleep_sessions" for t in cat["tables"])


def test_query_metric_daily_type_and_derived_column_with_receipt(v5):
    out = tools.query_metric("daily-resting-heart-rate", "2026-10-28", "2026-10-30", "mean")
    assert out["value"] == pytest.approx(62.0) and out["n"] == 3 and out["receipt"].startswith("r-")
    deep = tools.query_metric("sleep_sessions.deep_min", "2026-10-29", "2026-10-30", "daily")
    assert [r["value"] for r in deep["rows"]] == [60, 75]  # main sleep only, naps excluded
    assert tools.query_metric("weather_daily.temp_max_c", "2026-10-30", "2026-10-30", "max")["value"] == 31.4


def test_query_metric_rejects_unknown_names(v5):
    out = tools.query_metric("sleep_sessions.minutes_asleep; DROP TABLE x", "2026-10-01", "2026-10-30")
    assert "error" in out
    assert "error" in tools.query_metric("forecasts.p", "2026-10-01", "2026-10-30")


def test_weather_tool_has_no_location_argument():
    params = set(inspect.signature(tools.weather).parameters)
    assert params <= {"days_ahead", "days_back", "tool_context"}


def test_weather_tool_uses_session_location(monkeypatch):
    seen = []
    monkeypatch.setattr(weather, "forecast",
                        lambda lat, lon, **k: seen.append((lat, lon, k)) or [{"date": "2026-10-31"}])
    ctx = SimpleNamespace(state={"location": {"latitude": 13.08, "longitude": 80.27, "place": "Chennai"}})
    out = tools.weather(days_ahead=1, tool_context=ctx)  # type: ignore[arg-type]
    assert seen[-1][:2] == (13.08, 80.27) and out["place"] == "Chennai"
    out = tools.weather()  # no session location: the home location from settings
    assert seen[-1][:2] == (pytest.approx(11.341), pytest.approx(77.7172)) and out["place"] == "Erode"


def test_weather_tool_explains_an_outage(monkeypatch):
    def boom(*a, **k):
        raise weather.WeatherError("URLError")

    monkeypatch.setattr(weather, "forecast", boom)
    assert "unavailable" in tools.weather()["error"]


def test_sql_allows_new_tables_and_still_blinds_ledger(tmp_path):
    path = tmp_path / "h.db"
    make_db(path).close()
    for table in ("sleep_sessions", "exercise_sessions", "night_vitals", "activity_breakdown",
                  "hr_zone_thresholds", "weather_daily"):
        assert table in sqlguard.ALLOWED_TABLES
        conn, _ = sqlguard.guarded_connect(path)
        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        conn.close()
    conn, denied = sqlguard.guarded_connect(path)
    with pytest.raises(sqlite3.Error):
        conn.execute("SELECT * FROM forecasts").fetchall()
    conn.close()


def test_sandbox_bundle_carries_detail_frames(v5):
    from datetime import date

    from health_agents import bundle

    with tools._ro_connect() as conn:
        b = bundle.build(conn, date(2026, 10, 30))
    assert {"sleep_sessions", "weather_daily"} <= set(b["frames"])
    assert json.dumps(b["frames"]["sleep_sessions"])
