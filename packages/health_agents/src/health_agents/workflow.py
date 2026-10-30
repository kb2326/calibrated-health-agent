"""The chat agent as an ADK graph workflow, in two topologies behind one setting.

    single:  screen -> answer -> verify_receipts -> done
    multi:   screen -> route -> dispatch -> specialist(s) -> collect -> synthesize
                    -> verify_receipts -> done

`screen` and `verify_receipts` are deterministic. Verification checks every number in the
draft answer against this turn's tool outputs (`verify.numbers_without_receipts`); an
answer with unbacked numbers goes back once with feedback, and if it still has them it is
returned with an explicit "unverified: ..." footer, never passed off as checked.

In the multi topology routing is a graph edge chosen from the router's structured output,
so every specialist runs `single_turn` and nothing depends on LLM-to-LLM transfer
(ADR 0001). Both topologies share tools, instructions and the model setting.
"""
from __future__ import annotations

from typing import Any, Literal

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.models.base_llm import BaseLlm
from google.adk.tools import load_memory
from google.adk.workflow import Workflow
from google.genai import types
from health_core.settings import get_settings
from pydantic import BaseModel

from . import api_tools, instructions, memory, tools
from .verify import numbers_without_receipts

Topology = Literal["single", "multi"]
SPECIALISTS = ("data_scientist", "domain_expert", "health_coach")
TURN_OUTPUTS = "turn_outputs"
MAX_QUESTION = 2000
MAX_RETRIES = 1
REFUSAL = "Please ask a question about your health data (up to 2,000 characters)."

Model = str | BaseLlm


class _Route(BaseModel):
    specialists: list[str]


def _note_output(tool: Any, args: dict, tool_context: Any, tool_response: Any) -> None:
    """after_tool_callback: keep every tool result of this turn for verification."""
    outputs = list(tool_context.state.get(TURN_OUTPUTS, []))
    outputs.append(tool_response)
    tool_context.state[TURN_OUTPUTS] = outputs
    return None


ALL_TOOLS = [
    tools.list_metrics, tools.describe_substrate, tools.get_metric_series, tools.compare_periods,
    tools.get_anomalies, tools.get_correlations, tools.get_journal, tools.run_sql,
    tools.run_python, tools.get_scoreboard, api_tools.sources_for_metric, api_tools.list_devices,
    api_tools.get_health_profile, memory.save_fact_tool, load_memory,
]


def _agent(name: str, model: Model, instruction: str, agent_tools: list | None = None,
           **kw: Any) -> LlmAgent:
    return LlmAgent(name=name, model=model, instruction=instruction, tools=agent_tools or [],
                    after_tool_callback=_note_output if agent_tools else None, **kw)


def specialists(model: Model, models: dict[str, Model] | None = None) -> dict[str, LlmAgent]:
    models = models or {}
    return {
        "data_scientist": _agent(
            "data_scientist", models.get("data_scientist", model),
            instructions.SHARED + instructions.DATA_SCIENTIST + instructions.RECEIPTS,
            [tools.list_metrics, tools.describe_substrate, tools.get_metric_series,
             tools.compare_periods, tools.get_anomalies, tools.get_correlations,
             tools.get_journal, tools.run_sql, tools.run_python, tools.get_scoreboard,
             api_tools.sources_for_metric], mode="single_turn"),
        "domain_expert": _agent(
            "domain_expert", models.get("domain_expert", model),
            instructions.SHARED + instructions.DOMAIN_EXPERT + instructions.RECEIPTS,
            [tools.list_metrics, tools.get_metric_series, tools.get_anomalies,
             tools.get_correlations, api_tools.sources_for_metric, api_tools.list_devices,
             api_tools.get_health_profile], mode="single_turn"),
        "health_coach": _agent(
            "health_coach", models.get("health_coach", model),
            instructions.SHARED + instructions.COACH + instructions.RECEIPTS,
            [tools.get_metric_series, tools.compare_periods, tools.get_journal,
             tools.get_anomalies, tools.list_metrics, memory.save_fact_tool, load_memory],
            mode="single_turn"),
    }


def _text(node_input: Any) -> str:
    if isinstance(node_input, types.Content):
        return "".join(p.text or "" for p in node_input.parts or [])
    return "" if node_input is None else str(node_input)


def screen(ctx: Context, node_input: Any) -> str:
    question = _text(node_input).strip()
    if not question or len(question) > MAX_QUESTION:
        ctx.route = "refuse"
        return REFUSAL
    ctx.state["question"] = question
    ctx.state[TURN_OUTPUTS] = []
    ctx.state[tools.TURN_RECEIPTS] = []
    ctx.state["verify_attempts"] = 0
    ctx.route = "ok"
    return question


def verify_receipts(ctx: Context, node_input: Any) -> str:
    answer = _text(node_input).strip()
    unbacked = numbers_without_receipts(answer, list(ctx.state.get(TURN_OUTPUTS, [])),
                                        str(ctx.state.get("question", "")))
    attempts = int(ctx.state.get("verify_attempts", 0))
    if unbacked and attempts < MAX_RETRIES:
        ctx.state["verify_attempts"] = attempts + 1
        ctx.route = "retry"
        question = ctx.state.get("question", "")
        return (f"The person asked: {question}\n\nYour draft answer was:\n{answer}\n\n"
                f"These numbers in it have no tool result behind them: {', '.join(unbacked)}. "
                "Compute them with run_sql or run_python (citing the receipt id) or leave them "
                "out. Then reply to the person with the complete answer to their question, "
                "not a note about the numbers.")
    ctx.route = "done"
    return answer + (f"\n\nunverified: {', '.join(unbacked)}" if unbacked else "")


def done(node_input: Any) -> str:
    return _text(node_input)


def refuse(node_input: Any) -> str:
    return _text(node_input)


def dispatch(ctx: Context, node_input: Any) -> str:
    chosen = node_input.get("specialists", []) if isinstance(node_input, dict) else []
    plan = [s for s in dict.fromkeys(chosen) if s in SPECIALISTS][:3] or ["data_scientist"]
    ctx.state["plan"] = plan[1:]
    ctx.state["notes"] = []
    ctx.route = plan[0]
    return f"Question: {ctx.state.get('question', '')}"


def collect(ctx: Context, node_input: Any) -> str:
    notes = list(ctx.state.get("notes", []))
    notes.append(_text(node_input))
    ctx.state["notes"] = notes
    plan = list(ctx.state.get("plan", []))
    question = ctx.state.get("question", "")
    colleague_notes = "\n\n".join(f"Note {i + 1}:\n{n}" for i, n in enumerate(notes))
    if plan:
        ctx.state["plan"] = plan[1:]
        ctx.route = plan[0]
        return f"Question: {question}\n\nYour colleagues' notes so far:\n{colleague_notes}"
    ctx.route = "synthesize"
    return f"Question: {question}\n\nColleagues' notes:\n{colleague_notes}"


def build_workflow(topology: Topology | None = None, *, model: Model | None = None,
                   models: dict[str, Model] | None = None,
                   tools: list | None = None) -> Workflow:
    """`tools` replaces the single agent's tool list (the eval ablation's variants)."""
    topology = topology or get_settings().topology
    model = model or get_settings().model_default
    models = models or {}
    if topology == "single":
        answer = _agent("answer", models.get("answer", model),
                        instructions.SHARED + instructions.SINGLE,
                        ALL_TOOLS if tools is None else tools)
        return Workflow(name="health_agent_single", edges=[
            ("START", screen), (screen, {"ok": answer, "refuse": refuse}),
            (answer, verify_receipts), (verify_receipts, {"retry": answer, "done": done}),
        ])
    route = LlmAgent(name="route", model=models.get("route", model),
                     instruction=instructions.ROUTER, output_schema=_Route)
    team = specialists(model, models)
    synth = LlmAgent(name="synthesize", model=models.get("synthesize", model),
                     instruction=instructions.SHARED + instructions.SYNTHESIZER)
    edges: list = [
        ("START", screen), (screen, {"ok": route, "refuse": refuse}), (route, dispatch),
        (dispatch, dict(team)),
        *((agent, collect) for agent in team.values()),
        (collect, {**team, "synthesize": synth}),
        (synth, verify_receipts), (verify_receipts, {"retry": synth, "done": done}),
    ]
    return Workflow(name="health_agent_multi", edges=edges)
