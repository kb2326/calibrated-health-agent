# ADR 0001 — Phase 3 agent workflow shape on ADK 2.12

**Status:** accepted, 2026-10-23
**Context:** design spec `docs/superpowers/specs/2026-10-23-phase-3-agent-core-design.md` §4.1 and §12.7.
The chat agent is a graph `Workflow` with deterministic nodes around LLM nodes, in two
topologies (single agent; router → specialists → synthesizer). Before building on it, a
spike had to prove the pinned `google-adk==2.12.0` supports that shape.

## What the spike proved (`tests/test_workflow_spike.py`, fake model, no network)

| Check | Result |
|---|---|
| (a) `START → function node → LlmAgent → function node` runs; the last node receives the agent's output | pass |
| (b) a tool inside the `LlmAgent` writes `state["turn_receipts"]`; the verify node reads it | pass |
| (c) the verify node sets `ctx.route = "retry"` and an edge map `{retry: agent, done: …}` sends it back to the agent exactly once | pass |
| (d) a router `LlmAgent` with `output_schema` feeds a function node that sets `ctx.route` to a specialist; only that specialist runs | pass |

## Decision

**Verdict: `graph`.** Build both topologies as graph `Workflow`s:
`screen → answer → verify_receipts` with a `retry` route from verify back to the answer node,
and the multi topology's routing as a graph edge map driven by a structured router output.
All specialists are `single_turn`; there is no LLM-to-LLM transfer, which settles the delegation-mode
question left open in Phase 1.

## Consequences

- A specialist node receives the previous node's output as its input, not the user's question.
  The dispatch node therefore passes the original question (from state) to the chosen specialist.
- The investigator uses the same pattern (deterministic pick → LLM → deterministic validate).
- No fallback path is needed; the spike tests stay as regression tests for ADK upgrades.
