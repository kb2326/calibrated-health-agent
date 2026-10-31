"""The chat agent: one capable agent in a tool loop, wrapped in deterministic guards.

    screen (code) -> answer agent (Gemini, thinking on, ReAct tool loop) -> verify_receipts
    (code) -> done, and on an unbacked number back to the same agent once.

This is the pattern Anthropic, Google and OpenAI recommend for open-ended Q&A over data:
start from a single agent with good tools and add agents only where they measurably help.
The agent discovers what data exists (`data_catalog`) instead of reading a fixed list,
computes with `query_metric`, `run_sql` or `run_python`, and plans first (Gemini's built-in
thinking via ADK's `BuiltInPlanner`).

`team` (alias `multi`) adds two specialists as tools (ADK `AgentTool`): a coach and a domain
expert. The main agent may consult them, the orchestrator-workers pattern, and stays
responsible for every number. The earlier fixed router -> specialists -> synthesizer
pipeline was retired in Phase 4.5: its retry reached a node with no tools, and in the
owner's labelling it failed 14 of 30 answers (ADR 0007).

`screen` and `verify_receipts` are plain code, so the rules that matter don't depend on the
model following a prompt. The check compares every number in the draft with this turn's
tool outputs, and counts numbers implied by the question or by dates as backed. A draft with
unbacked numbers gets one revision. After that it is returned with a quiet note naming the
figures that weren't computed (`verify.note`), never passed off as checked.
"""
from __future__ import annotations

from typing import Any, Literal

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.models.base_llm import BaseLlm
from google.adk.planners import BuiltInPlanner
from google.adk.tools import load_memory
from google.adk.tools.agent_tool import AgentTool
from google.adk.workflow import Workflow
from google.genai import types
from health_core.settings import get_settings

from . import api_tools, instructions, memory, tools, tracing
from .verify import note, numbers_without_receipts

Topology = Literal["single", "team", "multi"]
TURN_OUTPUTS = "turn_outputs"
MAX_QUESTION = 2000
MAX_RETRIES = 1
REFUSAL = "Please ask a question about your health data (up to 2,000 characters)."

Model = str | BaseLlm


def _note_output(tool: Any, args: dict, tool_context: Any, tool_response: Any) -> None:
    """after_tool_callback: keep every tool result of this turn for verification."""
    outputs = list(tool_context.state.get(TURN_OUTPUTS, []))
    outputs.append(tool_response)
    tool_context.state[TURN_OUTPUTS] = outputs
    tracing.annotate_tool(args, tool_response)
    return None


ALL_TOOLS = [
    tools.data_catalog, tools.query_metric, tools.weather,
    tools.list_metrics, tools.describe_substrate, tools.get_metric_series, tools.compare_periods,
    tools.get_anomalies, tools.get_correlations, tools.get_journal, tools.run_sql,
    tools.run_python, tools.get_scoreboard, api_tools.sources_for_metric, api_tools.list_devices,
    api_tools.get_health_profile, memory.save_fact_tool, load_memory,
]
# Specialists read; only the main agent saves memory or runs code.
COACH_TOOLS = [tools.data_catalog, tools.query_metric, tools.get_journal, tools.weather,
               tools.compare_periods]
EXPERT_TOOLS = [tools.data_catalog, tools.query_metric, api_tools.sources_for_metric,
                api_tools.list_devices, api_tools.get_health_profile]


def _planner() -> BuiltInPlanner:
    budget = get_settings().agent_thinking_budget
    return BuiltInPlanner(thinking_config=types.ThinkingConfig(thinking_budget=budget))


def _agent(name: str, model: Model, instruction: str, agent_tools: list, *,
           description: str = "", planner: bool = True) -> LlmAgent:
    return LlmAgent(name=name, model=model, instruction=instruction, description=description,
                    tools=agent_tools, after_tool_callback=_note_output,
                    planner=_planner() if planner else None)


def specialist_tools(model: Model, models: dict[str, Model] | None = None) -> list[AgentTool]:
    models = models or {}
    coach = _agent("coach", models.get("coach", model),
                   instructions.SHARED + instructions.COACH, COACH_TOOLS, planner=False,
                   description="A health coach: practical next steps tied to the person's "
                               "recent data and journal (training load, recovery, sleep habits).")
    expert = _agent("domain_expert", models.get("domain_expert", model),
                    instructions.SHARED + instructions.DOMAIN_EXPERT, EXPERT_TOOLS, planner=False,
                    description="A health-data expert: what a metric means, typical ranges, "
                                "why devices or sources disagree.")
    return [AgentTool(agent=coach), AgentTool(agent=expert)]


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
    question = str(ctx.state.get("question", ""))
    unbacked = numbers_without_receipts(answer, list(ctx.state.get(TURN_OUTPUTS, [])), question)
    attempts = int(ctx.state.get("verify_attempts", 0))
    if unbacked and attempts < MAX_RETRIES:
        ctx.state["verify_attempts"] = attempts + 1
        ctx.route = "retry"
        return (f"The person asked: {question}\n\nYour draft answer was:\n{answer}\n\n"
                f"These numbers in it have no tool result behind them: {', '.join(unbacked)}. "
                "Compute them with query_metric, run_sql or run_python (citing the receipt id) "
                "or leave them out. Then reply to the person with the complete answer to their "
                "question, not a note about the numbers.")
    ctx.route = "done"
    return answer + note(unbacked)


def done(node_input: Any) -> str:
    return _text(node_input)


def refuse(node_input: Any) -> str:
    return _text(node_input)


def build_workflow(topology: Topology | None = None, *, model: Model | None = None,
                   models: dict[str, Model] | None = None,
                   tools: list | None = None) -> Workflow:
    """`tools` replaces the main agent's tool list (the eval ablation's variants)."""
    topology = topology or get_settings().topology
    team = topology in ("team", "multi")
    model = model or get_settings().model_default
    models = models or {}
    agent_tools = list(ALL_TOOLS if tools is None else tools)
    instruction = instructions.SHARED + instructions.SINGLE
    if team:
        agent_tools += specialist_tools(model, models)
        instruction += instructions.TEAM
    answer = _agent("answer", models.get("answer", model), instruction, agent_tools)
    return Workflow(name="health_agent_team" if team else "health_agent_single", edges=[
        ("START", screen), (screen, {"ok": answer, "refuse": refuse}),
        (answer, verify_receipts), (verify_receipts, {"retry": answer, "done": done}),
    ])


def answer_agent(wf: Workflow) -> LlmAgent:
    """The main agent node of a built workflow (tests and the ablation inspect it)."""
    for edge in wf.edges:
        for node in edge if isinstance(edge, tuple) else (edge,):
            if isinstance(node, LlmAgent) and node.name == "answer":
                return node
    raise LookupError("workflow has no answer agent")
