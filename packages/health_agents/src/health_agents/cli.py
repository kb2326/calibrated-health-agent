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
import os
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import typer
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from health_core.settings import get_settings
from health_data import store

from . import agent_db, costs, memory, receipts, tools
from .workflow import build_workflow

app = typer.Typer(add_completion=False, help="Ask the Calibrated Health Agent.")
memory_app = typer.Typer(invoke_without_command=True, help="What the agent remembers.")
app.add_typer(memory_app, name="memory")

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


def _model() -> str | BaseLlm:
    """The chat model: Gemini on Vertex AI (global endpoint), owner credentials."""
    settings = get_settings()
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", settings.gcp_project)
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", settings.vertex_location)
    return settings.model_default


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

    def __init__(self, model: str | BaseLlm | None = None):
        self.service = InMemorySessionService()
        self.memory = memory.HealthMemoryService()
        self.runner = Runner(app_name=APP_NAME, node=build_workflow(model=model or _model()),
                             session_service=self.service, memory_service=self.memory)
        self.session_id = uuid.uuid4().hex

    async def _ask(self, question: str, confirm: Callable[[dict], bool]) -> TurnResult:
        if not await self.service.get_session(app_name=APP_NAME, user_id="owner",
                                              session_id=self.session_id):
            await self.service.create_session(app_name=APP_NAME, user_id="owner",
                                              session_id=self.session_id)
        result = TurnResult(answer="")
        message: types.Content | None = types.Content(role="user", parts=[types.Part(text=question)])
        while message is not None:
            pending = []
            async for ev in self.runner.run_async(user_id="owner", session_id=self.session_id,
                                                  new_message=message):
                if ev.usage_metadata is not None:
                    result.input_tokens += ev.usage_metadata.prompt_token_count or 0
                    result.output_tokens += ev.usage_metadata.candidates_token_count or 0
                if isinstance(ev.output, str):
                    result.answer = ev.output
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
        return result

    def ask(self, question: str, confirm: Callable[[dict], bool] = _confirm_with_typer) -> TurnResult:
        if costs.chat_month_spend() >= get_settings().chat_monthly_usd_cap:
            raise BudgetReached(f"Monthly chat budget (${get_settings().chat_monthly_usd_cap:.2f}) "
                                "reached; resets on the 1st.")
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
