"""The `cha` terminal: ask, receipt, memory, with per-turn cost and a monthly chat cap."""
from __future__ import annotations

import pytest
from agent_fakes import FakeLlm, call, text
from health_agents import agent_db, cli, memory, tools
from health_core.settings import Settings
from health_data import db, store
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture(autouse=True)
def fixture_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(store, "_gen_path", lambda p: tmp_path / ".db_generation")
    monkeypatch.setattr(tools, "get_settings", lambda: Settings.model_validate({"db_bucket": None}))
    monkeypatch.setattr(cli, "get_settings", lambda: Settings.model_validate(
        {"db_bucket": None, "data_dir": tmp_path}))
    db.init_db()
    with db.connect() as conn:
        conn.execute("INSERT INTO daily_metrics (date, data_type, agg_value, n_points, source)"
                     " VALUES ('2026-10-20', 'steps', 8000, 1, '')")


def _use(monkeypatch, script):
    llm = FakeLlm(script)
    monkeypatch.setattr(cli, "_model", lambda: llm)
    return llm


def test_ask_prints_answer_receipts_and_cost(monkeypatch):
    _use(monkeypatch, [call("run_sql", query="SELECT SUM(agg_value) AS s FROM daily_metrics"),
                       text("You walked 8000 steps")])
    out = runner.invoke(cli.app, ["ask", "how many steps?"])
    assert out.exit_code == 0, out.output
    assert "8000 steps" in out.output and "receipts: r-" in out.output and "$" in out.output


def test_chat_cap_refuses(monkeypatch):
    llm = _use(monkeypatch, [text("x")])
    with agent_db.connect() as conn:
        conn.execute("INSERT INTO chat_usage (month, input_tokens, output_tokens, usd, created_at)"
                     " VALUES (?, 0, 0, 0.30, 't')", (cli.costs.this_month(),))
    out = runner.invoke(cli.app, ["ask", "anything"])
    assert "Monthly chat budget" in out.output and llm.calls == 0


def test_ask_records_chat_spend(monkeypatch):
    _use(monkeypatch, [text("hello")])
    runner.invoke(cli.app, ["ask", "hi"])
    assert cli.costs.chat_month_spend() > 0


def test_receipt_command_shows_code_and_reruns(monkeypatch):
    rid = tools.run_sql("SELECT SUM(agg_value) AS s FROM daily_metrics")["receipt"]
    out = runner.invoke(cli.app, ["receipt", rid, "--rerun"])
    assert out.exit_code == 0 and "SELECT SUM(agg_value)" in out.output and "matches" in out.output


def test_receipt_unknown_id():
    out = runner.invoke(cli.app, ["receipt", "r-0000000000"])
    assert out.exit_code == 1 and "no such receipt" in out.output


def test_ask_confirms_save_fact(monkeypatch):
    _use(monkeypatch, [call("save_fact", text="I started a new job"), text("Saved it.")])
    out = runner.invoke(cli.app, ["ask", "remember I started a new job"], input="y\n")
    assert out.exit_code == 0, out.output
    with agent_db.connect() as conn:
        assert conn.execute("SELECT text FROM facts").fetchall() == [("I started a new job",)]


def test_memory_list_and_forget():
    fid = memory.save_fact_now("likes morning runs")
    out = runner.invoke(cli.app, ["memory"])
    assert fid in out.output and "likes morning runs" in out.output
    out = runner.invoke(cli.app, ["memory", "forget", fid])
    assert out.exit_code == 0 and "forgotten" in out.output
