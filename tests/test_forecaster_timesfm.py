"""Forecaster 5: TimesFM through BigQuery AI.FORECAST (fake client; no network)."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from health_ledger import dist, forecasters
from health_ledger.forecasters import timesfm
from ledger_fixtures import journal, make_db

D = date(2026, 10, 30)


class FakeBQ:
    def __init__(self, rows=None, error: Exception | None = None):
        self.rows, self.error, self.calls = rows or [], error, []

    def query(self, sql, job_config=None):
        self.calls.append((sql, job_config))
        if self.error:
            raise self.error
        return SimpleNamespace(result=lambda: self.rows)


def _row(day: date, value: float, lo: float, hi: float):
    return SimpleNamespace(forecast_timestamp=datetime(day.year, day.month, day.day, tzinfo=UTC),
                           forecast_value=value, prediction_interval_lower_bound=lo,
                           prediction_interval_upper_bound=hi)


@pytest.fixture
def conn(tmp_path):
    c = make_db(tmp_path / "t.db")
    for i in range(1, 16):
        journal(c, D - timedelta(days=i), 5, 6, 3)
    yield c
    c.close()


def test_registered_after_statistical():
    names = list(forecasters.FORECASTERS)
    assert names.index("timesfm") == names.index("statistical") + 1


def test_timesfm_maps_interval_to_distribution(conn):
    fake = FakeBQ([_row(D, 7.0, 7.0 - 1.2816, 7.0 + 1.2816)])
    f = timesfm.forecast(conn, D, {}, client=fake)
    assert f.abstain == {} and set(f.probs) == {"mood", "energy", "soreness"}
    assert f.probs["energy"] == pytest.approx(dist.discretized_normal(7.0, 1.0))
    sql, config = fake.calls[0]
    assert "AI.FORECAST" in sql and "UNNEST(@rows)" in sql
    assert config.maximum_bytes_billed == timesfm.MAX_BYTES_BILLED
    assert "horizon => 1," in sql  # last outcome was D-1; an int literal, never user text


def test_timesfm_abstains_below_14(tmp_path):
    c = make_db(tmp_path / "t.db")
    for i in range(1, 14):
        journal(c, D - timedelta(days=i), 5, 6, 3)
    fake = FakeBQ()
    f = timesfm.forecast(c, D, {}, client=fake)
    assert f.abstain["energy"] == "fewer than 14 outcomes" and fake.calls == []


def test_timesfm_error_abstains_with_type_only(conn):
    f = timesfm.forecast(conn, D, {}, client=FakeBQ(error=RuntimeError("secret detail 7.5")))
    assert f.abstain == dict.fromkeys(("mood", "energy", "soreness"), "bigquery error: RuntimeError")


def test_timesfm_missing_day_row_abstains(conn):
    f = timesfm.forecast(conn, D, {}, client=FakeBQ([_row(D - timedelta(days=3), 5, 4, 6)]))
    assert f.abstain["mood"] == "no forecast row for the day"
