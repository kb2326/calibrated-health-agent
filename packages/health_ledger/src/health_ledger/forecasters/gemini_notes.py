"""Forecaster 7: forecaster 6 plus the investigator's live hypotheses, and nothing else.

Pre-registered in docs/ledger/analysis-plan.md as a secondary endpoint (7 vs 6 on energy).
The prompt is exactly forecaster 6's, followed by one notes section that is always present
("none yet" when there is nothing), so 7's prompt has one fixed shape. The model, schema
and temperature are forecaster 6's (`gemini.bet`). The notes are up to five hypotheses
created before the lock whose latest status is not refuted or retired: supported first,
then open, newest first. Their statements were written by a model from untrusted inputs,
so each is wrapped. The lock stores the notes and hashes them into the day's chain entry.

The cloud agent budget (`Settings.agent_cloud_monthly_usd_cap`, shared with the
investigator) is checked first: when spent, 7 abstains with `budget`.

The hypothesis tables belong to `health_agents`, but this package must not import it, so
the selection is a small query here and the wrapping a private copy of `untrusted.wrap`
(tested byte-identical).
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from health_core.settings import get_settings
from health_data import db

from health_ledger.forecasters import gemini
from health_ledger.forecasters.base import Forecast

FORECASTER_ID = f"gemini_notes:{get_settings().forecast_model}"
MAX_NOTES = 5
HEADER = "Your own notes from past misses (associations, may be wrong):"
NONE_YET = "Your own notes from past misses: none yet."


def _wrap(source: str, text: str) -> str:
    escaped = text.replace("</untrusted", "&lt;/untrusted").replace("<untrusted", "&lt;untrusted")
    return f'<untrusted source="{source}">{escaped}</untrusted>'


def notes_for_lock(conn: sqlite3.Connection, before: str) -> list[dict]:
    try:
        rows = conn.execute(
            "SELECT h.id, h.statement, s.status, s.n_cond, h.created_at FROM hypotheses h "
            "JOIN hypothesis_status s ON s.hypothesis_id = h.id AND s.id = "
            "(SELECT MAX(id) FROM hypothesis_status WHERE hypothesis_id = h.id) "
            "WHERE s.status NOT IN ('refuted', 'retired') AND h.created_at < ?", (before,)).fetchall()
    except sqlite3.OperationalError:  # a database from before schema v4
        return []
    rows.sort(key=lambda r: r[4], reverse=True)
    rows.sort(key=lambda r: 0 if r[2] == "supported" else 1)
    return [{"id": i, "statement": st, "status": s, "n": n} for i, st, s, n, _ in rows[:MAX_NOTES]]


def prompt(snapshot: dict, notes: list[dict]) -> str:
    if not notes:
        return gemini.prompt(snapshot) + "\n\n" + NONE_YET
    lines = [f"{_wrap('hypothesis', n['statement'])} (status: {n['status']}, n={n['n']})"
             for n in notes]
    return gemini.prompt(snapshot) + "\n\n" + HEADER + "\n" + "\n".join(lines)


def _month_spend(conn: sqlite3.Connection, month: str) -> float:
    try:
        row = conn.execute("SELECT COALESCE(SUM(usd), 0) FROM agent_runs WHERE substr(day, 1, 7) = ?",
                           (month,)).fetchone()
    except sqlite3.OperationalError:
        return 0.0
    return float(row[0])


def forecast(conn: sqlite3.Connection, day: date, snapshot: dict, *, client: Any = None) -> Forecast:
    settings = get_settings()
    if _month_spend(conn, day.isoformat()[:7]) >= settings.agent_cloud_monthly_usd_cap:
        return Forecast.abstain_all("budget")
    notes = notes_for_lock(conn, db.utc_stamp())
    result, usage = gemini.bet(prompt(snapshot, notes), client=client, label="gemini_notes")
    return Forecast(probs=result.probs, abstain=result.abstain,
                    inputs={"notes": notes, "usage": usage})
