"""The same ADK workflow as `cha ask`, wrapped for AG-UI.

The web adds no intelligence: `build_workflow()` with the same tools, caps and receipts.

Client state is untrusted. ag-ui-adk copies a run's `state` into the ADK session, so a
browser could otherwise set keys the workflow trusts (`turn_outputs`, `last_draft`, ...).
`sanitise_state` keeps only a validated device `location`, which the `weather` tool reads
from the session; the model never sees or sets it.
"""
from __future__ import annotations

import math
from collections.abc import AsyncGenerator
from typing import Any

from ag_ui.core import RunAgentInput
from ag_ui_adk import ADKAgent
from google.adk.apps import App
from google.adk.models import BaseLlm
from health_agents import memory
from health_agents.cli import APP_NAME
from health_agents.workflow import build_workflow

PLACE_MAX = 60


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


class HealthAgent(ADKAgent):
    """ADKAgent whose runs carry only sanitised client state."""

    async def run(self, input: RunAgentInput, *args: Any, **kwargs: Any) -> AsyncGenerator:  # type: ignore[override]
        clean = input.model_copy(update={"state": sanitise_state(input.state)})
        async for event in super().run(clean, *args, **kwargs):
            yield event


def build_agent(*, topology: str | None = None, model: BaseLlm | str | None = None,
                models: dict[str, BaseLlm | str] | None = None) -> HealthAgent:
    wf = build_workflow(topology, model=model, models=models)  # type: ignore[arg-type]
    app = App(name=APP_NAME, root_agent=wf)  # type: ignore[arg-type]
    agent = HealthAgent.from_app(app, user_id="owner", memory_service=memory.HealthMemoryService())
    return agent  # type: ignore[return-value]
