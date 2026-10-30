"""`cha`: the owner's terminal into the agent.

    cha ask "how did I sleep this week?"   one question
    cha chat                               a conversation (one session)
    cha receipt r-1a2b3c4d5e [--rerun]     the code behind a number; re-run it
    cha memory [forget ID]                 what the agent remembers

Every answer prints its receipt ids, tokens and estimated cost. A monthly chat budget
(`Settings.chat_monthly_usd_cap`) refuses further questions once spent. Gemini is called
on Vertex AI with the owner's credentials (`GOOGLE_APPLICATION_CREDENTIALS` / ADC).
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from health_core.settings import get_settings
from health_data import civil, db, store

from . import agent_db, costs, memory, receipts, tools, vertex
from .workflow import Topology, build_workflow

app = typer.Typer(add_completion=False, help="Ask the Calibrated Health Agent.")
memory_app = typer.Typer(invoke_without_command=True, help="What the agent remembers.")
app.add_typer(memory_app, name="memory")
notes_app = typer.Typer(invoke_without_command=True, help="What the investigator found.")
app.add_typer(notes_app, name="notes")
STALE_JOURNAL_DAYS = 2
SMOKE_QUESTIONS = Path("evals/smoke/questions.yaml")

APP_NAME = "cha"
CONFIRM = "adk_request_confirmation"
_RECEIPT_ID = re.compile(r"\br-[0-9a-f]{10}\b")


class BudgetReached(RuntimeError):
    pass


@dataclass
class TurnResult:
    answer: str
    receipts: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    tool_calls: list[dict] = field(default_factory=list)  # {name, args, response}


def _model() -> str | BaseLlm:
    """The chat model: Gemini on Vertex AI (global endpoint), owner credentials."""
    vertex.configure()
    return get_settings().model_default


def _confirm_with_typer(args: dict) -> bool:
    original = args.get("originalFunctionCall") or {}
    detail = json.dumps(original.get("args") or {}, ensure_ascii=False)
    return typer.confirm(f"The agent wants to {original.get('name', 'act')}: {detail}. Allow?",
                         default=False)


def _stale_note() -> str | None:
    settings = get_settings()
    if not settings.db_bucket:
        return None
    try:
        remote = store.remote_generation(settings.db_bucket, settings.db_object)
    except Exception:
        return "note: could not reach the bucket to check this copy is current"
    if remote != store.recorded_generation():
        return "note: the local database is behind the bucket; run `cha-data db pull`"
    return None


class Session:
    """One ADK runner + session, reused across the turns of `cha chat`."""

    def __init__(self, model: str | BaseLlm | None = None, *, refresh_memory: bool = True,
                 tools: list | None = None, topology: Topology | None = None):
        self.refresh_memory = refresh_memory
        self.service = InMemorySessionService()
        self.memory = memory.HealthMemoryService()
        self.runner = Runner(app_name=APP_NAME,
                             node=build_workflow(topology, model=model or _model(), tools=tools),
                             session_service=self.service, memory_service=self.memory)
        self.session_id = uuid.uuid4().hex

    async def _ask(self, question: str, confirm: Callable[[dict], bool]) -> TurnResult:
        if not await self.service.get_session(app_name=APP_NAME, user_id="owner",
                                              session_id=self.session_id):
            await self.service.create_session(app_name=APP_NAME, user_id="owner",
                                              session_id=self.session_id)
        result = TurnResult(answer="")
        calls: dict[str, dict] = {}
        message: types.Content | None = types.Content(role="user", parts=[types.Part(text=question)])
        while message is not None:
            pending = []
            async for ev in self.runner.run_async(user_id="owner", session_id=self.session_id,
                                                  new_message=message):
                if ev.usage_metadata is not None:
                    result.input_tokens += ev.usage_metadata.prompt_token_count or 0
                    result.output_tokens += ((ev.usage_metadata.candidates_token_count or 0)
                                             + (ev.usage_metadata.thoughts_token_count or 0))
                if isinstance(ev.output, str):
                    result.answer = ev.output
                for fc in ev.get_function_calls():
                    if fc.name != CONFIRM:
                        calls[fc.id or str(len(calls))] = {"name": fc.name, "args": dict(fc.args or {}),
                                                           "response": None}
                for fr in ev.get_function_responses():
                    if fr.id in calls:
                        calls[fr.id]["response"] = fr.response
                pending += [fc for fc in ev.get_function_calls() if fc.name == CONFIRM]
            message = None
            if pending:
                message = types.Content(role="user", parts=[types.Part(
                    function_response=types.FunctionResponse(
                        id=fc.id, name=CONFIRM, response={"confirmed": confirm(dict(fc.args or {}))}))
                    for fc in pending])
        session = await self.service.get_session(app_name=APP_NAME, user_id="owner",
                                                 session_id=self.session_id)
        turn = (session.state.get(tools.TURN_RECEIPTS, []) if session else []) or []
        ids = [r["receipt"] for r in turn] + _RECEIPT_ID.findall(result.answer)
        result.receipts = list(dict.fromkeys(ids))
        result.tool_calls = list(calls.values())
        return result

    def ask(self, question: str, confirm: Callable[[dict], bool] = _confirm_with_typer) -> TurnResult:
        if costs.chat_month_spend() >= get_settings().chat_monthly_usd_cap:
            raise BudgetReached(f"Monthly chat budget (${get_settings().chat_monthly_usd_cap:.2f}) "
                                "reached; resets on the 1st.")
        if self.refresh_memory:
            try:
                with tools._ro_connect() as conn:
                    self.memory.refresh_episodes(conn)
            except Exception:
                pass  # offline or no embeddings yet: memory search falls back to recent episodes
        result = asyncio.run(self._ask(question, confirm))
        result.usd = costs.record_chat(result.input_tokens, result.output_tokens)
        return result


def _print_turn(result: TurnResult) -> None:
    typer.echo(result.answer)
    typer.echo("")
    typer.echo("receipts: " + (", ".join(result.receipts) if result.receipts else "none"))
    typer.echo(f"tokens {result.input_tokens} in / {result.output_tokens} out · "
               f"${result.usd:.4f}")


@app.command()
def ask(question: str) -> None:
    """Ask one question about your health data."""
    note = _stale_note()
    if note:
        typer.echo(note)
    try:
        _print_turn(Session().ask(question))
    except BudgetReached as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from None


@app.command()
def chat() -> None:
    """A conversation; an empty line ends it."""
    note = _stale_note()
    if note:
        typer.echo(note)
    session = Session()
    while True:
        question = typer.prompt("you", default="", show_default=False)
        if not question.strip():
            return
        try:
            _print_turn(session.ask(question))
        except BudgetReached as exc:
            typer.echo(str(exc))
            return


@app.command()
def receipt(receipt_id: str, rerun: bool = typer.Option(False, "--rerun")) -> None:
    """Show the code behind a number, and optionally re-run it."""
    found = receipts.get(receipt_id)
    if found is None:
        typer.echo(f"no such receipt: {receipt_id}")
        raise typer.Exit(1)
    r, where = found
    typer.echo(f"{r.id} · {r.kind} · {r.executor} · as of {r.as_of} · {where}")
    typer.echo(r.code)
    typer.echo(f"output: {json.dumps(r.output, ensure_ascii=False)[:2000]}")
    if rerun:
        out = receipts.rerun(receipt_id)
        if "error" in out:
            typer.echo(f"re-run failed: {out['error']}")
            raise typer.Exit(1)
        if out["matches"]:
            typer.echo("re-run: matches")
        elif out["data_changed"]:
            typer.echo("re-run: data changed since (late sync or backfill); new value: "
                       f"{json.dumps(out['new'], ensure_ascii=False)[:2000]}")
        else:
            typer.echo("re-run: DIFFERENT on the same data: "
                       f"{json.dumps(out['new'], ensure_ascii=False)[:2000]}")


@memory_app.callback()
def memory_list(ctx: typer.Context) -> None:
    """List remembered facts and episodes."""
    if ctx.invoked_subcommand:
        return
    with agent_db.connect() as conn:
        facts = conn.execute("SELECT id, text, valid_from, valid_to FROM facts ORDER BY valid_from").fetchall()
        n_episodes = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
    for fid, text, since, until in facts:
        typer.echo(f"{fid}  {text}  (from {since}{' to ' + until if until else ''})")
    typer.echo(f"{len(facts)} facts, {n_episodes} episodes")


@memory_app.command("forget")
def memory_forget(item_id: str) -> None:
    """Delete one fact or episode."""
    if memory.forget(item_id):
        typer.echo(f"{item_id} forgotten")
    else:
        typer.echo(f"nothing called {item_id}")
        raise typer.Exit(1)


def _persist(fn: Callable[[], object]) -> object:
    """Write to the local health.db and push it, under health_data's write guard."""
    from health_data.cli import _run_persisted

    return _run_persisted(fn)


def _pull_quietly() -> None:
    settings = get_settings()
    if not settings.db_bucket:
        return
    try:
        store.check_pull_safe(db.DB_PATH)
        store.pull_db(settings.db_bucket, settings.db_object, db.DB_PATH)
    except Exception as exc:  # offline, or unpushed local work: show what is here
        typer.echo(f"note: showing the local copy ({type(exc).__name__} while pulling)")


@notes_app.callback()
def notes_list(ctx: typer.Context, all_: bool = typer.Option(False, "--all")) -> None:
    """Hypotheses new or changed since you last looked."""
    if ctx.invoked_subcommand:
        return
    _pull_quietly()
    with agent_db.connect() as aconn:
        row = aconn.execute("SELECT value FROM notes_seen WHERE key = 'last_viewed'").fetchone()
    since = "" if all_ or row is None else row[0]
    with tools._ro_connect() as conn:
        shown = 0
        for hid, statement, created_at, receipt_ids in conn.execute(
                "SELECT id, statement, created_at, receipt_ids_json FROM hypotheses ORDER BY created_at"):
            latest = conn.execute(
                "SELECT status, n_cond, n_other, effect, p_value, created_at FROM hypothesis_status"
                " WHERE hypothesis_id = ? ORDER BY id DESC LIMIT 1", (hid,)).fetchone()
            changed = max(created_at, latest[5] if latest else "")
            if changed <= since:
                continue
            status, n_cond, n_other, effect, p = latest[:5] if latest else ("open", 0, 0, None, None)
            effect_txt = "" if effect is None else f", effect {effect:+.2f}, p {p:.3f}"
            typer.echo(f"{hid}  [{status}]  {statement}")
            typer.echo(f"    n = {n_cond} vs {n_other}{effect_txt} · receipts {', '.join(json.loads(receipt_ids))}")
            shown += 1
        last = conn.execute("SELECT MAX(date) FROM journal_outcome").fetchone()[0]
    if not shown:
        typer.echo("nothing new from the investigator")
    gap = None if last is None else (civil.today() - date.fromisoformat(last)).days
    if gap is None or gap >= STALE_JOURNAL_DAYS:
        typer.echo("No journal for " + ("any day yet" if gap is None else f"{gap} days")
                   + " — nothing new to learn from.")
    with agent_db.connect() as aconn:
        aconn.execute("INSERT INTO notes_seen VALUES ('last_viewed', ?) ON CONFLICT(key) DO UPDATE"
                      " SET value = excluded.value", (db.utc_stamp(),))


@notes_app.command("retire")
def notes_retire(hypothesis_id: str) -> None:
    """Stop a hypothesis from being used (kept in the ledger, marked retired)."""
    from . import hypotheses

    def run() -> bool:
        with db.connect() as conn:
            return hypotheses.retire(conn, hypothesis_id, civil.today())

    if _persist(run):
        typer.echo(f"{hypothesis_id} retired")
    else:
        typer.echo(f"no hypothesis {hypothesis_id}")
        raise typer.Exit(1)


@app.command()
def smoke(topology: Annotated[str, typer.Option("--topology")] = "single",
          questions: Annotated[Path, typer.Option("--questions")] = SMOKE_QUESTIONS,
          report_file: Annotated[Path | None, typer.Option("--report")] = None) -> None:
    """Phase 3 exit check on a synthetic database with the real model (costs cents)."""
    import tempfile

    from . import smoke as smoke_mod

    with tempfile.TemporaryDirectory(prefix="cha-smoke-", ignore_cleanup_errors=True) as tmp:
        report = smoke_mod.run_smoke(smoke_mod.load_questions(questions), topology=topology,
                                     workdir=Path(tmp))
    if report_file is not None:  # synthetic data only: safe to keep the full answers
        report_file.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    for r in report["results"]:
        typer.echo(f"{'PASS' if r['ok'] else 'FAIL'}  {r['question']}  {r['reason']}")
        typer.echo(f"      receipts: {', '.join(r['receipts']) or 'none'}")
    typer.echo(f"{report['passed']}/{report['total']} passed · ${report['usd']:.4f}")
    if report["passed"] != report["total"]:
        raise typer.Exit(1)
