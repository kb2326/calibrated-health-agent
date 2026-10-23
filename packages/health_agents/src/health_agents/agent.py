"""ADK agent: an orchestrator over three specialists (ADR-008).

The structure follows Google Research's Personal Health Agent, which
decomposes health support into a Data Science agent, a Domain Expert, and a
Health Coach beneath a routing orchestrator, and beat both single-agent and
parallel multi-agent baselines on expert evaluation.

Two published failure modes shaped the instructions below:

- Google's own Gemini health coach is criticised for not anchoring on data
  it already holds — asking users about metrics already logged. Every
  specialist here is told to query the substrate before asking anything.
- Wearable analysis needs multi-step numerical reasoning that defeats a
  plain LLM; the tool-based approach reached 84% accuracy where narration
  fails. Hence `run_sql`: compute the number, never estimate it.

The whole tool surface is read-only. Not by instruction — by construction:
tools open SQLite in `mode=ro` and every API call passes the client's
method allowlist.
"""
from __future__ import annotations

from google.adk.agents import LlmAgent
from health_core.settings import get_settings

from . import api_tools, instructions, tools

MODEL = get_settings().model_default

# Delegation mode of each specialist, set explicitly rather than left to ADK's
# default. `LlmAgent(mode=...)` accepts "chat" | "task" | "single_turn"
# (google-adk 2.12.0; https://adk.dev/agents/llm-agents/ and the field
# docstring in google.adk.agents.llm_agent.LlmAgent). Phase 1 uses
# "single_turn" for all three: they complete a job without chatting with the
# user, and "task" mode is unavailable inside graph workflows. Final modes are
# decided with the Phase 3 workflow design.
SUB_AGENT_MODE = "single_turn"

data_scientist = LlmAgent(
    name="data_scientist",
    model=MODEL,
    mode=SUB_AGENT_MODE,
    description=(
        "Statistical analysis of the health time series. Handles trends, "
        "comparisons between periods, outliers, correlations, and any "
        "question needing an actual computed number."
    ),
    instruction=instructions.SHARED + instructions.DATA_SCIENTIST,
    tools=[
        tools.list_metrics, tools.describe_substrate, tools.get_metric_series,
        tools.compare_periods, tools.get_anomalies, tools.get_correlations,
        tools.get_journal, tools.run_sql, tools.get_scoreboard,
        api_tools.sources_for_metric,
    ],
    output_key="analysis",
)

domain_expert = LlmAgent(
    name="domain_expert",
    model=MODEL,
    mode=SUB_AGENT_MODE,
    description=(
        "Physiological and metric interpretation. Explains what a metric "
        "means, what ranges are typical, and how measurements are derived "
        "or why two sources disagree."
    ),
    instruction=instructions.SHARED + instructions.DOMAIN_EXPERT,
    tools=[
        tools.list_metrics, tools.get_metric_series, tools.get_anomalies,
        tools.get_correlations, api_tools.sources_for_metric,
        api_tools.list_devices, api_tools.get_health_profile,
    ],
    output_key="interpretation",
)

health_coach = LlmAgent(
    name="health_coach",
    model=MODEL,
    mode=SUB_AGENT_MODE,
    description=(
        "Behavioural support: goals, habits, and what to do next, grounded "
        "in the person's own trends and their subjective journal."
    ),
    instruction=instructions.SHARED + instructions.COACH,
    tools=[
        tools.get_metric_series, tools.compare_periods, tools.get_journal,
        tools.get_anomalies, tools.list_metrics,
    ],
    output_key="coaching",
)

root_agent = LlmAgent(
    name="health_orchestrator",
    model=MODEL,
    description="Routes personal health questions to the right specialist.",
    instruction=instructions.ORCHESTRATOR,
    sub_agents=[data_scientist, domain_expert, health_coach],
)
