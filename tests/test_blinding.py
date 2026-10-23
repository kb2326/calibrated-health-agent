"""Blinding: no owner-facing surface shows a bet before its day is settled."""
from __future__ import annotations

import pytest
from health_agents import tools
from health_core.settings import Settings
from health_data import db, store
from health_ledger import chain, lock
from health_ledger.forecasters import Forecast


@pytest.fixture(autouse=True)
def ledger_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(store, "_gen_path", lambda p: tmp_path / ".db_generation")
    monkeypatch.setattr(tools, "get_settings", lambda: Settings.model_validate({"db_bucket": None}))
    db.init_db()
    from datetime import UTC, datetime

    with db.connect() as conn:
        chain.ensure_plan_hash(conn, "ab")
        lock.lock_today(conn, datetime(2026, 10, 30, 6, 30, tzinfo=UTC), {
            "a": lambda c, d, s: Forecast(probs=dict.fromkeys(
                ("mood", "energy", "soreness"), tuple([0.1] * 10)))})


@pytest.mark.parametrize("query", [
    "SELECT * FROM forecasts",
    'SELECT * FROM "Forecasts"',
    "SELECT * FROM [snapshots]",
    "SELECT payload_json FROM ledger",
    "SELECT rps FROM scores",
    "SELECT * FROM journal_outcome /* harmless */ JOIN forecasts USING (day)",
    "SELECT * FROM daily_metrics -- \n UNION SELECT * FROM forecasts",
    "WITH x AS (SELECT * FROM FORECASTS) SELECT * FROM x",
])
def test_run_sql_blocks_ledger_tables(query):
    result = tools.run_sql(query)
    assert result["rows"] == [] and "ledger" in result["error"]


def test_run_sql_still_reads_other_tables():
    assert "error" not in tools.run_sql("SELECT COUNT(*) AS n FROM daily_metrics")


def test_get_scoreboard_has_no_unsettled_days():
    board = tools.get_scoreboard()
    assert board["days_locked"] == 1 and board["days_scored"] == 0
    assert board["forecasters"] == [] and board["primary"]["n"] == 0


def test_cli_status_prints_no_probabilities():
    from health_ledger.cli import app
    from typer.testing import CliRunner

    result = CliRunner().invoke(app, ["status"])
    assert result.exit_code == 0
    assert "days locked: 1" in result.output and "chain: ok" in result.output
    assert "0.1" not in result.output and "probs" not in result.output


def test_cli_verify_exit_codes():
    from health_ledger.cli import app
    from typer.testing import CliRunner

    assert CliRunner().invoke(app, ["verify"]).exit_code == 0
