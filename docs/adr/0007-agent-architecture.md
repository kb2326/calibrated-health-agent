# ADR 0007: One tool-loop agent with thinking; specialists as tools

**Status:** accepted (Phase 4.5), 2026-10-31. Supersedes the multi-agent shape in ADR 0001.

## Context

The owner labelled 110 answers. 32 failed, and error analysis traced them to the design, not
the model:

- **The fixed multi-agent pipeline broke.** Router → specialists → synthesizer: the number
  check sent its one revision to the synthesizer, which has no tools. It answered "I cannot
  verify", printed tool calls as text and invented a tool name. 14 of 30 failed.
- **Rigidity.**
  - A fixed metric list baked into the prompt.
  - An alarming `unverified:` footer on correct answers ("30" in "last 30 days" for "last
    month").
  - Refusals ("I'm not a clinician") on ordinary training questions.

The owner asked for "standard, current, proven architectures, not old-school rigidity".

## Decision

1. **One capable agent in a ReAct tool loop.** This is the default that Anthropic ("Building
   effective agents"), Google ADK and OpenAI's agent guide recommend for open-ended Q&A:
   start with a single agent and good tools, and add agents only where they measurably help.
2. **Thinking on.** ADK's `BuiltInPlanner` with Gemini's native thinking, capped at 512
   tokens (`agent_thinking_budget`), so the agent plans the computation first.
3. **Just-in-time context (a semantic layer).** `data_catalog` lists every metric and detail
   table with meaning, unit, coverage and gaps. The agent discovers what exists instead of
   reading a fixed list.
4. **Code as the main analysis tool.** `query_metric` handles simple reads; `run_sql` and
   `run_python` handle the rest. Every number keeps its receipt (ADR 0003).
5. **Specialists as tools, not a pipeline.** In `team` (alias `multi`) a coach and a domain
   expert are ADK `AgentTool`s the main agent *may* consult (orchestrator-workers). It stays
   responsible for every number.
6. **Deterministic guards.** `screen` and the grounding check stay as plain code. Window
   lengths and day counts between stated dates count as backed. An empty draft is retried,
   and the last real draft is used if needed. After one revision, an unbacked figure gets a
   quiet note instead of a footer.
7. **A lean toolbox.** Overlapping tools were dropped, because every tool description is
   re-sent at each step.
8. **Helpful-first instructions.** Compute on the days that exist and name the gap. Give real
   wellness guidance. Never diagnose; escalate red flags.

## Consequences

- About $0.01 per question (5–8 model calls with thinking), inside the $0.30 chat cap at
  personal volume.
- Single versus team is decided by evidence: the owner's labelled questions are re-run on both
  and compared with a blind pairwise judge, and the result goes in ADR 0005.
- The forecast ledger's agent (forecaster 7) and the investigator are unaffected.
