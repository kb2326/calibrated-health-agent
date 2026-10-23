"""What the agent layer spends, against the owner's monthly caps.

Prices are per million tokens from `Settings` (verified at deploy). Laptop chat spend is
recorded in `agent.db`; the cloud job's (investigator + forecaster 7) in `health.db`'s
`agent_runs`. Months are the owner's civil months.
"""
from __future__ import annotations

import sqlite3

from health_core.settings import get_settings
from health_data import civil, db

from . import agent_db


def usd(input_tokens: int, output_tokens: int) -> float:
    s = get_settings()
    return (input_tokens * s.price_in_per_m + output_tokens * s.price_out_per_m) / 1_000_000


def this_month() -> str:
    return civil.today().strftime("%Y-%m")


def chat_month_spend() -> float:
    with agent_db.connect() as conn:
        row = conn.execute("SELECT COALESCE(SUM(usd), 0) FROM chat_usage WHERE month = ?",
                           (this_month(),)).fetchone()
    return float(row[0])


def record_chat(input_tokens: int, output_tokens: int) -> float:
    cost = usd(input_tokens, output_tokens)
    with agent_db.connect() as conn:
        conn.execute("INSERT INTO chat_usage (month, input_tokens, output_tokens, usd, created_at)"
                     " VALUES (?, ?, ?, ?, ?)",
                     (this_month(), input_tokens, output_tokens, cost, db.utc_stamp()))
    return cost


def cloud_month_spend(conn: sqlite3.Connection) -> float:
    row = conn.execute("SELECT COALESCE(SUM(usd), 0) FROM agent_runs WHERE substr(day, 1, 7) = ?",
                       (this_month(),)).fetchone()
    return float(row[0])
