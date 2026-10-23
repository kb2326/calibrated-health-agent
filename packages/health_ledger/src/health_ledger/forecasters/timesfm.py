"""Forecaster 5: Google's TimesFM foundation model, through BigQuery `AI.FORECAST`.

Per target, the outcome history (date, value) goes in as a query parameter and is read
with `UNNEST(@rows)`: no table is created and no data is stored in BigQuery. TimesFM
forecasts to day D; its 80% prediction interval maps to a normal with
sd = (upper - lower) / (2 * 1.2816), discretized onto 1..10.

Cost: the query reads no stored table, so it bills ~0 bytes, inside the 1 TiB monthly
free tier. Every query also sets `maximum_bytes_billed`, so a surprise fails (the
forecaster abstains) instead of billing. Errors abstain with the exception type only.

`python -m health_ledger.forecasters.timesfm --selftest` runs one query on synthetic
numbers against the configured project (owner credentials) to prove the SQL works.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, date, datetime, timedelta
from typing import Any

from health_core.settings import get_settings

from health_ledger import dist
from health_ledger.forecasters.base import Forecast
from health_ledger.forecasters.baselines import outcome_history

MIN_OUTCOMES = 14
CONFIDENCE = 0.8
Z80 = 1.2816  # half-width of a central 80% normal interval, in sds
MAX_BYTES_BILLED = 100 * 1024 * 1024
TIMEOUT_SECONDS = 60  # a hung query abstains instead of holding the job to its 15-min limit

SQL = """
SELECT forecast_timestamp, forecast_value,
       prediction_interval_lower_bound, prediction_interval_upper_bound
FROM AI.FORECAST(
  (SELECT d, v FROM UNNEST(@rows)),
  data_col => 'v', timestamp_col => 'd',
  horizon => {horizon}, confidence_level => {confidence})
ORDER BY forecast_timestamp
"""


def _client() -> Any:
    from google.cloud import bigquery

    return bigquery.Client(project=get_settings().gcp_project)


def _query(client: Any, rows: list[tuple[date, int]], horizon: int) -> list[Any]:
    from google.cloud import bigquery

    params = [bigquery.StructQueryParameter(
        None,
        bigquery.ScalarQueryParameter("d", "TIMESTAMP", datetime(d.year, d.month, d.day, tzinfo=UTC)),
        bigquery.ScalarQueryParameter("v", "FLOAT64", float(v)),
    ) for d, v in rows]
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("rows", "STRUCT", params)],
        maximum_bytes_billed=MAX_BYTES_BILLED,
    )
    sql = SQL.format(horizon=int(horizon), confidence=CONFIDENCE)
    return list(client.query(sql, job_config=config).result(timeout=TIMEOUT_SECONDS))


def forecast(conn: sqlite3.Connection, day: date, snapshot: dict, *, client: Any = None) -> Forecast:
    probs, abstain = {}, {}
    for target, rows in outcome_history(conn, day).items():
        if len(rows) < MIN_OUTCOMES:
            abstain[target] = f"fewer than {MIN_OUTCOMES} outcomes"
            continue
        try:
            client = client or _client()
            result = _query(client, rows, (day - rows[-1][0]).days)
        except Exception as exc:  # never log the message: it can echo parameter values
            abstain[target] = f"bigquery error: {type(exc).__name__}"
            continue
        row = next((r for r in result if r.forecast_timestamp.date() == day), None)
        if row is None:
            abstain[target] = "no forecast row for the day"
            continue
        sd = (row.prediction_interval_upper_bound - row.prediction_interval_lower_bound) / (2 * Z80)
        probs[target] = dist.discretized_normal(float(row.forecast_value), float(sd))
    return Forecast(probs=probs, abstain=abstain)


def _selftest() -> int:
    start = date(2026, 1, 1)
    rows = [(start + timedelta(days=i), 5 + (i % 3)) for i in range(30)]
    result = _query(_client(), rows, 1)
    print([round(float(r.forecast_value), 2) for r in result])
    return 0


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else 2)
