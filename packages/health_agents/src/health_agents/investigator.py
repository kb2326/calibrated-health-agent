"""The nightly investigator: study the biggest new miss with code, propose hypotheses.

Runs in the cloud job after settle and re-test. Steps:

1. **Which days are new:** scored days (`outcome` ledger entries) not yet covered by an
   earlier run. None: nothing to do, no model call, no cost. After a gap, one run covers
   all of them.
2. **Budget:** if the month's cloud agent spend has reached the cap, skip (and mark the
   days covered so they aren't retried).
3. **Pick one miss** (`pick_miss`): the largest RPS of forecaster 6 among the new days.
4. **Investigate** (one Flash-Lite agent with `run_python` over the investigator bundle and
   the guarded `run_sql`), under hard caps: model calls, tool calls, input and output tokens,
   and wall time. A capped run proposes nothing.
5. **Validate** each proposal (`hypotheses.validate`); at most two are stored.

The agent sees only settled days: the bundle is cut at the latest settled day and the SQL
guard refuses the ledger's tables, so an unsettled forecast never reaches it. Notes and
existing hypothesis statements arrive wrapped as untrusted text. Every run (other than
"nothing new") appends one `agent_runs` row; a failure is recorded and never raised.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from health_core.settings import get_settings
from health_data import civil, db
from health_ledger.forecasters import gemini

from . import bundle, costs, hypotheses, instructions, receipts, tools, vertex
from .untrusted import UNTRUSTED_RULE, wrap

MAX_CALLS = 6
MAX_TOOL_CALLS = 6
# At $0.30 / $2.50 per million tokens a capped night costs at most ~$0.0095, so even a
# run every night stays inside the $0.30 monthly cloud cap.
MAX_INPUT_TOKENS = 15_000
MAX_OUTPUT_TOKENS = 2_000
WALL_SECONDS = 180
MAX_STORED = 2
# The investigator leaves room in the shared monthly cap for forecaster 7's remaining daily
# bets (measured ~$0.00075 a call), so 7 never abstains with "budget" because of it.
FORECASTER7_DAILY_USD = 0.001
CONTEXT_DAYS = 14
EMPTY = '{"hypotheses": []}'


def _uncovered(conn: sqlite3.Connection) -> list[str]:
    covered: set[str] = set()
    for (days,) in conn.execute("SELECT covered_days_json FROM agent_runs WHERE kind = 'investigate'"):
        covered.update(json.loads(days or "[]"))
    scored = [r[0] for r in conn.execute("SELECT day FROM ledger WHERE kind = 'outcome' ORDER BY day")]
    return [d for d in scored if d not in covered]


def pick_miss(conn: sqlite3.Connection, days: list[str]) -> tuple[str, str] | None:
    marks = ",".join("?" * len(days))
    row = conn.execute(f"SELECT day, target FROM scores WHERE forecaster = ? AND day IN ({marks}) "
                       "ORDER BY rps DESC, day DESC, target LIMIT 1",
                       (gemini.FORECASTER_ID, *days)).fetchone()
    if row is None:  # forecaster 6 abstained on these days: the worst mean miss instead
        row = conn.execute(f"SELECT day, target FROM scores WHERE day IN ({marks}) GROUP BY day,"
                           " target ORDER BY AVG(rps) DESC, day DESC LIMIT 1", days).fetchone()
    return (row[0], row[1]) if row else None


def forecaster7_reserve(now: datetime) -> float:
    """Dollars to keep for forecaster 7 until the end of the owner's month (today included)."""
    today = now.astimezone(civil.zone()).date()
    first_next = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    return (first_next - today).days * FORECASTER7_DAILY_USD


def _record_run(conn: sqlite3.Connection, today: str, covered: list[str], usage: dict,
                outcome: str) -> float:
    usd = costs.usd(usage["in"], usage["out"])
    conn.execute("INSERT INTO agent_runs (day, kind, covered_days_json, calls, input_tokens,"
                 " output_tokens, usd, outcome, created_at) VALUES (?, 'investigate', ?, ?, ?, ?,"
                 " ?, ?, ?)", (today, json.dumps(sorted(covered)), usage["calls"], usage["in"],
                               usage["out"], usd, outcome, db.utc_stamp()))
    conn.commit()
    return usd


def _context(conn: sqlite3.Connection, day: str, target: str, as_of: date) -> str:
    data = bundle.build(conn, as_of, investigator=True)
    recent = data["frames"]["days"][-CONTEXT_DAYS:]
    notes = [r for r in data["frames"]["journal"] if r["date"] >= recent[0]["day"]] if recent else []
    misses = [m for m in data["frames"]["misses"] if m["day"] == day and m["target"] == target]
    probs = conn.execute("SELECT probs_json FROM forecasts f JOIN scores s USING (day, forecaster,"
                         " target) WHERE day = ? AND target = ? AND forecaster = ?",
                         (day, target, gemini.FORECASTER_ID)).fetchone()
    on_file = [f"- {wrap('hypothesis', h['statement'])} (status: {h['status']}, n={h['n']})"
               for h in hypotheses.live(conn)]
    note_lines = [f"- {n['date']} tags={n['tags']}: {n['note'] or '(no note)'}" for n in notes]
    return "\n\n".join([
        f"The miss: {target} on {day}. The person rated it {misses[0]['outcome'] if misses else '?'}.",
        "Forecaster RPS that day (lower is better): " + json.dumps(
            {m["forecaster"]: round(m["rps"], 3) for m in misses}),
        f"Forecaster 6's distribution over 1..10: {probs[0] if probs else 'abstained'}",
        "Last two weeks (lock-time columns plus outcomes):\n" + json.dumps(recent, default=str),
        "Journal notes and tags, same window:\n" + ("\n".join(note_lines) or "(none)"),
        "Hypotheses already on file:\n" + ("\n".join(on_file) or "(none)"),
    ])


def _parse(text: str) -> list[hypotheses.Proposal]:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return []
    out = []
    for item in (data.get("hypotheses") or [])[:MAX_STORED] if isinstance(data, dict) else []:
        if isinstance(item, dict) and all(isinstance(item.get(k), str) for k in
                                          ("statement", "target", "direction", "condition_code")):
            out.append(hypotheses.Proposal(item["statement"], item["target"], item["direction"],
                                           item["condition_code"]))
    return out


def _agent(conn: sqlite3.Connection, as_of: date, model: str | BaseLlm, usage: dict) -> LlmAgent:
    def run_python(code: str) -> dict:
        """Run pandas code over days, journal, metrics and misses; assign `result`."""
        out = tools.run_python_on(conn, code, as_of, investigator=True)
        if "error" in out:
            return out
        rid = receipts.record(conn, kind="python", code=code, data_hash=out["data_hash"],
                              as_of=out["as_of"], output=out["result"],
                              executor=receipts.SANDBOX, context="investigator")
        return {"result": out["result"], "stdout": wrap("sandbox_output", out["stdout"]) or "",
                "receipt": rid}

    def run_sql(query: str) -> dict:
        """One read-only SELECT (the ledger's tables are blinded)."""
        out = tools.guarded_query(query)
        if "error" in out:
            return out
        rid = receipts.record(conn, kind="sql", code=out["code"],
                              data_hash=receipts.rows_hash(out["rows"]), as_of=as_of.isoformat(),
                              output=out["rows"], executor=receipts.SQLITE, context="investigator")
        return {"rows": out["rows"], "n": len(out["rows"]), "receipt": rid}

    def before_model(callback_context: Any, llm_request: Any) -> LlmResponse | None:
        if (usage["calls"] >= MAX_CALLS or usage["in"] >= MAX_INPUT_TOKENS
                or usage["out"] >= MAX_OUTPUT_TOKENS):
            usage["capped"] = True
            return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=EMPTY)]))
        usage["calls"] += 1
        return None

    def after_model(callback_context: Any, llm_response: LlmResponse) -> None:
        meta = llm_response.usage_metadata
        if meta is not None:
            usage["in"] += meta.prompt_token_count or 0
            usage["out"] += (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)
        return None

    def before_tool(tool: Any, args: dict, tool_context: Any) -> dict | None:
        usage["tools"] += 1
        if usage["tools"] > MAX_TOOL_CALLS:
            return {"error": "tool budget reached; give your final JSON now"}
        return None

    return LlmAgent(name="investigator", model=model,
                    instruction=UNTRUSTED_RULE + "\n" + instructions.INVESTIGATOR,
                    tools=[run_python, run_sql], before_model_callback=before_model,
                    after_model_callback=after_model, before_tool_callback=before_tool)


async def _investigate(agent: LlmAgent, prompt: str) -> str:
    sessions = InMemorySessionService()
    runner = Runner(app_name="investigator", agent=agent, session_service=sessions)
    session = await sessions.create_session(app_name="investigator", user_id="job")
    final = ""
    async for ev in runner.run_async(user_id="job", session_id=session.id, new_message=types.Content(
            role="user", parts=[types.Part(text=prompt)])):
        if ev.content and ev.content.parts:
            texts = [p.text for p in ev.content.parts if p.text]
            if texts:
                final = "".join(texts)
    return final


def run_investigation(conn: sqlite3.Connection, now: datetime, *, llm: BaseLlm | None = None) -> dict:
    vertex.configure()
    today = now.astimezone(civil.zone()).date().isoformat()
    new_days = _uncovered(conn)
    if not new_days:
        return {"result": "skipped (nothing new)", "proposals": 0, "stored": 0, "covered": [],
                "usd": 0.0}
    usage = {"calls": 0, "tools": 0, "in": 0, "out": 0, "capped": False}
    cap = get_settings().agent_cloud_monthly_usd_cap - forecaster7_reserve(now)
    if costs.cloud_month_spend(conn, today[:7]) >= cap:
        _record_run(conn, today, new_days, usage, "skipped (budget)")
        return {"result": "skipped (budget)", "proposals": 0, "stored": 0, "covered": new_days,
                "usd": 0.0}
    try:
        miss = pick_miss(conn, new_days)
        as_of = bundle.latest_settled_day(conn)
        if miss is None or as_of is None:
            usd = _record_run(conn, today, new_days, usage, "skipped (no scores)")
            return {"result": "skipped (no scores)", "proposals": 0, "stored": 0,
                    "covered": new_days, "usd": usd}
        agent = _agent(conn, as_of, llm or get_settings().model_default, usage)
        final = asyncio.run(asyncio.wait_for(
            _investigate(agent, _context(conn, miss[0], miss[1], as_of)), WALL_SECONDS))
        proposals = [] if usage["capped"] else _parse(final)
        stored = 0
        for proposal in proposals:
            hid, _reason = hypotheses.validate(conn, proposal, as_of)
            stored += hid is not None
        outcome = "capped" if usage["capped"] else "done"
        usd = _record_run(conn, today, new_days, usage, outcome)
        return {"result": outcome, "proposals": len(proposals), "stored": stored,
                "covered": new_days, "usd": usd, "miss": list(miss)}
    except Exception as exc:  # contained: the job carries on without hypotheses tonight
        conn.rollback()
        usd = _record_run(conn, today, new_days, usage, "failed")
        return {"result": "failed", "error": type(exc).__name__, "proposals": 0, "stored": 0,
                "covered": new_days, "usd": usd}
