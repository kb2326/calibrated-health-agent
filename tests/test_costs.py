"""Spend accounting behind the monthly caps."""
from __future__ import annotations

import pytest
from health_agents import agent_db, costs
from ledger_fixtures import make_db


def test_usd_uses_settings_prices():
    assert costs.usd(1_000_000, 0) == pytest.approx(0.10)
    assert costs.usd(0, 1_000_000) == pytest.approx(0.40)


def test_chat_spend_sums_this_month_only():
    costs.record_chat(1_000_000, 0)
    with agent_db.connect() as conn:
        conn.execute("INSERT INTO chat_usage (month, input_tokens, output_tokens, usd, created_at)"
                     " VALUES ('1999-01', 0, 0, 5.0, 't')")
    assert costs.chat_month_spend() == pytest.approx(0.10)


def test_cloud_spend_reads_agent_runs(tmp_path):
    conn = make_db(tmp_path / "h.db")
    month = costs.this_month()
    conn.execute("INSERT INTO agent_runs (day, kind, covered_days_json, calls, input_tokens,"
                 " output_tokens, usd, outcome, created_at) VALUES (?, 'investigate', '[]', 1, 1,"
                 " 1, 0.12, 'done', 't')", (f"{month}-05",))
    conn.execute("INSERT INTO agent_runs (day, kind, covered_days_json, calls, input_tokens,"
                 " output_tokens, usd, outcome, created_at) VALUES ('1999-01-05', 'forecast7',"
                 " '[]', 1, 1, 1, 9.0, 'done', 't')")
    assert costs.cloud_month_spend(conn) == pytest.approx(0.12)
