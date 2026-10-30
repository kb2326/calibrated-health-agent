# ADR 0005: Single agent stays the default until the ablation says otherwise

**Status:** accepted, pending the Phase 4 ablation result, 2026-10-30

## Context

Two topologies share tools, instructions and the model (ADR 0001):

- **single**: one agent with every tool;
- **multi**: a router, then data-scientist / domain-expert / coach specialists, then a
  synthesizer. It follows Google Research's Personal Health Agent design.

Multi-agent is treated as a hypothesis, not a feature. In the Phase 3 exit check (by reading),
single scored 10/10 and multi 7/10 on the smoke questions, at roughly 3× the model calls per
question.

## Decision

- `CHA_TOPOLOGY=single` is the default.
- The default changes only if `cha-eval ablation` shows **multi better than single** on
  the paired cases: exact McNemar p < 0.05, a positive paired-bootstrap interval, and a
  difference above the run's minimum detectable difference. It must also not regress on
  safety.
- The ablation report states the MDD, so "no difference" reads as "no difference this suite
  could detect", not "they are equal".

## Consequences

- With 20 ablation cases (the free-tier budget), the MDD is large (about 0.35 at an 80%
  pass rate). Only a big difference can switch the default. That's the honest outcome of a
  small suite, and it is reported as such.
- Results will be appended here when the ablation run lands.
