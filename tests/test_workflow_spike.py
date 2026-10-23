"""ADR 0001 gate: the ADK 2.12 graph shape the Phase 3 workflow relies on.

(a) function node -> LlmAgent node -> function node runs end to end;
(b) a tool call inside the LlmAgent leaves its output in state for the verify node;
(c) the verify node can route back to the agent once.
"""
from __future__ import annotations

import asyncio

from agent_fakes import FakeLlm, call, text
from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.tool_context import ToolContext
from google.adk.workflow import Workflow
from google.genai import types


def _run(workflow, message: str = "hi") -> tuple:
    async def go():
        sessions = InMemorySessionService()
        runner = Runner(app_name="spike", node=workflow, session_service=sessions)
        session = await sessions.create_session(app_name="spike", user_id="u")
        events = []
        async for ev in runner.run_async(user_id="u", session_id=session.id,
                                         new_message=types.Content(role="user", parts=[types.Part(text=message)])):
            events.append(ev)
        final = await sessions.get_session(app_name="spike", user_id="u", session_id=session.id)
        return events, final
    return asyncio.run(go())


def test_function_llm_function_graph_runs():
    seen = {}

    def screen(ctx: Context, node_input):
        ctx.state["screened"] = True
        return node_input

    def finish(ctx: Context, node_input):
        seen["final"] = node_input
        return node_input

    llm = FakeLlm([text("the answer is 4")])
    agent = LlmAgent(name="answer", model=llm, instruction="answer")
    wf = Workflow(name="wf", edges=[("START", screen, agent, finish)])
    _, session = _run(wf)
    assert session.state.get("screened") is True
    assert "4" in str(seen["final"])


def test_state_carries_receipt_outputs_to_verify():
    seen = {}

    def compute(tool_context: ToolContext) -> dict:
        """Compute a number."""
        receipts = list(tool_context.state.get("turn_receipts", []))
        receipts.append({"receipt": "r-1", "output": 6.4})
        tool_context.state["turn_receipts"] = receipts
        return {"value": 6.4, "receipt": "r-1"}

    def verify(ctx: Context, node_input):
        seen["receipts"] = ctx.state.get("turn_receipts")
        return node_input

    llm = FakeLlm([call("compute"), text("mean 6.4 [r-1]")])
    agent = LlmAgent(name="answer", model=llm, instruction="answer", tools=[compute])
    wf = Workflow(name="wf", edges=[("START", agent, verify)])
    _run(wf)
    assert seen["receipts"] == [{"receipt": "r-1", "output": 6.4}]


def test_verify_can_route_back_once():
    passes = []

    def verify(ctx: Context, node_input):
        passes.append(str(node_input))
        if len(passes) == 1:
            ctx.route = "retry"
        else:
            ctx.route = "done"
        return node_input

    def done(node_input):
        return node_input

    llm = FakeLlm([text("first 9.9"), text("second 6.4")])
    agent = LlmAgent(name="answer", model=llm, instruction="answer")
    wf = Workflow(name="wf", edges=[("START", agent, verify), (verify, {"retry": agent, "done": done})])
    _run(wf)
    assert len(passes) == 2 and llm.calls == 2


def test_structured_router_output_drives_a_route():
    from pydantic import BaseModel

    class Route(BaseModel):
        specialists: list[str]

    seen = {}

    def dispatch(ctx: Context, node_input):
        data = node_input if isinstance(node_input, dict) else node_input.model_dump()
        seen["route_input"] = data
        ctx.route = data["specialists"][0]
        return data

    router = LlmAgent(name="route", model=FakeLlm([text('{"specialists": ["coach"]}')]),
                      instruction="route", output_schema=Route)
    coach_llm = FakeLlm([text("coach says hi")])
    coach = LlmAgent(name="coach", model=coach_llm, instruction="coach")
    ds_llm = FakeLlm([text("ds")])
    ds = LlmAgent(name="ds", model=ds_llm, instruction="ds")
    wf = Workflow(name="wf", edges=[("START", router, dispatch), (dispatch, {"coach": coach, "ds": ds})])
    _run(wf)
    assert seen["route_input"] == {"specialists": ["coach"]}
    assert coach_llm.calls == 1 and ds_llm.calls == 0
