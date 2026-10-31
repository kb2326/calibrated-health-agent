"""The same ADK workflow as `cha ask`, wrapped for AG-UI.

The web adds no intelligence: `build_workflow()` with the same tools, caps and receipts.

Client state is untrusted. ag-ui-adk copies a run's `state` into the ADK session, so a
browser could otherwise set keys the workflow trusts (`turn_outputs`, `last_draft`, ...).
`sanitise_state` keeps only a validated device `location`, which the `weather` tool reads
from the session; the model never sees or sets it.
"""
from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncGenerator
from typing import Any

from ag_ui.core import EventType, RunAgentInput, RunErrorEvent, RunStartedEvent
from ag_ui_adk import ADKAgent
from google.adk.apps import App
from google.adk.models import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from health_agents import agent_db_sync, costs, memory
from health_agents.cli import APP_NAME
from health_agents.workflow import build_workflow
from health_core.settings import get_settings

from .stream import StreamFilter

PLACE_MAX = 60
_TURN_LOCK = asyncio.Lock()


def _coord(value: Any, limit: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value) or abs(value) > limit:
        return None
    return value


def sanitise_state(state: Any) -> dict[str, Any]:
    """Keep only {"location": {"latitude", "longitude", "place"?}} with sane values."""
    loc = state.get("location") if isinstance(state, dict) else None
    if not isinstance(loc, dict):
        return {}
    lat, lon = _coord(loc.get("latitude"), 90), _coord(loc.get("longitude"), 180)
    if lat is None or lon is None:
        return {}
    clean: dict[str, Any] = {"latitude": lat, "longitude": lon}
    place = loc.get("place")
    if isinstance(place, str) and place.strip():
        clean["place"] = place.strip()[:PLACE_MAX]
    return {"location": clean}


class ChatBudget(BasePlugin):
    """Records every model call's tokens against the monthly chat cap, as `cha ask` does."""

    def __init__(self) -> None:
        super().__init__(name="chat_budget")

    async def after_model_callback(self, *, callback_context: Any,
                                   llm_response: LlmResponse) -> LlmResponse | None:
        if llm_response.partial:  # streaming: chunks repeat the usage the final response carries
            return None
        u = llm_response.usage_metadata
        if u is not None:
            costs.record_chat(u.prompt_token_count or 0,
                              (u.candidates_token_count or 0) + (u.thoughts_token_count or 0))
        return None


def budget_message() -> str | None:
    cap = get_settings().chat_monthly_usd_cap
    if costs.chat_month_spend() >= cap:
        return f"Monthly chat budget (${cap:.2f}) reached; it resets on the 1st."
    return None


class HealthAgent(ADKAgent):
    """ADKAgent whose runs carry only sanitised client state, inside the chat budget."""

    async def run(self, input: RunAgentInput, *args: Any, **kwargs: Any) -> AsyncGenerator:  # type: ignore[override]
        # One turn at a time: a turn pulls, writes and pushes agent.db, and a second turn's
        # pull must not replace the file under the first. One owner, so this costs nothing.
        async with _TURN_LOCK:
            shared = agent_db_sync.shared_turn()  # same agent.db as the CLI when a bucket is set
            await asyncio.to_thread(shared.__enter__)
            try:
                refused = await asyncio.to_thread(budget_message)  # after the pull: current spend
                if refused:
                    yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=input.thread_id,
                                          run_id=input.run_id)
                    yield RunErrorEvent(type=EventType.RUN_ERROR, message=refused, code="BUDGET")
                    return
                clean = input.model_copy(update={"state": sanitise_state(input.state)})
                keep = StreamFilter()  # raw tool rows never reach the browser
                async for event in super().run(clean, *args, **kwargs):
                    out = keep(event)
                    if out is not None:
                        yield out
            finally:
                await asyncio.to_thread(shared.__exit__, None, None, None)


def build_agent(*, topology: str | None = None, model: BaseLlm | str | None = None,
                models: dict[str, BaseLlm | str] | None = None) -> HealthAgent:
    wf = build_workflow(topology, model=model, models=models)  # type: ignore[arg-type]
    app = App(name=APP_NAME, root_agent=wf, plugins=[ChatBudget()])  # type: ignore[arg-type]
    agent = HealthAgent.from_app(app, user_id="owner", memory_service=memory.HealthMemoryService())
    return agent  # type: ignore[return-value]
