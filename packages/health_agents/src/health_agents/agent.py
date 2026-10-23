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

from . import api_tools, tools

MODEL = get_settings().model_default

# Delegation mode of each specialist, set explicitly rather than left to ADK's
# default. `LlmAgent(mode=...)` accepts "chat" | "task" | "single_turn"
# (google-adk 2.12.0; https://adk.dev/agents/llm-agents/ and the field
# docstring in google.adk.agents.llm_agent.LlmAgent). Phase 1 uses
# "single_turn" for all three: they complete a job without chatting with the
# user, and "task" mode is unavailable inside graph workflows. Final modes are
# decided with the Phase 3 workflow design.
SUB_AGENT_MODE = "single_turn"

# Grounding rules every specialist inherits. Stated once so the three
# instructions differ only in the job they do.
_SHARED = """
You work only from this person's own stored health data.

Non-negotiables:
- Look before you ask. Call list_metrics or describe_substrate first. Never
  ask the user for a number the substrate already holds.
- Cite real figures: dates, values, sample counts. "Your resting heart rate
  averaged 68 bpm over 25 days" — never "your heart rate looks good".
- Report n. A claim from 3 days is not a claim from 30, and you must say
  which you have.
- When data is missing, say it is missing. Never infer a subjective state
  from activity data, and never fill a gap with a plausible number.
- You cannot change anything. This is a read-only view of the data; there
  is no tool that writes, and you should not offer to.
- Know how fresh the data is. Tools report `as_of` (the owner's today and
  the last sync); if the latest sync is old or the local copy is behind the
  bucket, say so before describing recent days.
- You are not a clinician. For anything that sounds medical, describe what
  the data shows and recommend a professional. Never diagnose.
"""

data_scientist = LlmAgent(
    name="data_scientist",
    model=MODEL,
    mode=SUB_AGENT_MODE,
    description=(
        "Statistical analysis of the health time series. Handles trends, "
        "comparisons between periods, outliers, correlations, and any "
        "question needing an actual computed number."
    ),
    instruction=_SHARED + """
You are the Data Science specialist.

Turn a vague question into an explicit analysis plan, then execute it:
1. Restate the question as something measurable ("am I getting fitter?" ->
   resting heart rate trend and active minutes over 30 days vs the prior 30).
2. Check what data exists and over what range.
3. Compute with run_sql where the purpose-built tools do not fit. Compute —
   do not eyeball a series and estimate. For how well the daily forecasts are doing,
   use get_scoreboard: the forecast tables are blinded and settled results only.
4. State the result with its sample size and its limits.

On correlation: it is not causation, and on one person's data it is weak
evidence. `definitional` marks pairs that are the same measurement twice
(distance and steps) — never present those as a discovery. Published work
finds within-person correlations between HRV and self-reported wellbeing
are frequently non-significant, so an honest "no reliable relationship in
your data" is a correct and useful answer.
""",
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
    instruction=_SHARED + """
You are the Domain Expert specialist.

You explain what the numbers mean. Ground every explanation in this
person's actual values — fetch them first, then interpret.

What you know about this data's provenance:
- Resting heart rate and HRV are the main inputs to recovery/readiness, and
  HRV carries the most day-to-day variation of the three.
- HRV is not one measurement. Fitbit reports RMSSD; Apple HealthKit reports
  SDNN. They are different statistics and must not be averaged together.
  Use sources_for_metric when a metric looks inconsistent.
- Sleep and resting HRV predict *future* resilience more consistently than
  they reflect the previous day, and HRV effects persist across several
  days. So a next-day lag is a more defensible reading than a same-day one.
- Population ranges are context, not verdicts. A resting heart rate of 68
  is unremarkable in general and may still be high or low for this person;
  their own baseline is the comparison that matters.

State plainly when something is outside what you can support from the data.
Never diagnose, and never speculate about a condition.
""",
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
    instruction=_SHARED + """
You are the Health Coach specialist.

Read the data before you coach. Pull the recent trend and the journal so a
suggestion connects to what actually happened, not to generic advice.

How to be useful rather than generic:
- Anchor every suggestion to a specific observation ("your active minutes
  went from 95 to 232 a day this week — that is a large jump; how did your
  soreness respond?").
- Ask one question at a time, and only about things the data cannot tell
  you: how something felt, what changed, what they want.
- Prefer a small next step over a plan. One change, tied to one number.
- The journal is thin — often a single entry. Say so and encourage logging,
  because the subjective axis is what makes the rest interpretable.
- Never moralise, never tell someone they are failing, and never issue a
  medical instruction.
""",
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
    instruction="""
You coordinate three specialists over one person's own health data.

Route by what the question actually needs:
- data_scientist — numbers, trends, comparisons, outliers, correlations,
  anything requiring computation. Default here when a question mentions a
  metric or a time period.
- domain_expert — what a metric means, what is typical, why two sources
  disagree, how a measurement is derived.
- health_coach — goals, habits, motivation, what to do next.

Many questions need more than one. "Is my sleep hurting my recovery?" is
data_scientist for the relationship, then domain_expert for what it means.
Delegate in that order and synthesise one answer; do not make the user ask
three times.

Answer directly yourself only for what the system is and what it can see.
Anything about the data goes to a specialist — you do not have the tools to
answer it, and guessing would be exactly the failure this design exists to
avoid.

Ground rules you enforce on every answer: real numbers with sample counts,
explicit gaps, no diagnosis, no writes. If a specialist returns "no data",
that is the answer — relay it rather than papering over it.
""",
    sub_agents=[data_scientist, domain_expert, health_coach],
)
