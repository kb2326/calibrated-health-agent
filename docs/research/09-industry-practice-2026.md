# 09 — Industry practice for agent projects (2025–2026)

Researched 2026-10-24 for the Phase 4/5 redesign. The aim: present and build the project the
way practitioners do. It is a **personal portfolio project** on the owner's own data, not a
product and not a replacement for any commercial service.

**Owner direction (2026-10-24):** the **agent answering questions** is the front door; the
**forecasting experiment** is the second act and the evidence. Both must be industry
quality. The final front door is the **web app** (Phase 7, Next.js + AG-UI) with a
synthetic-data demo, not a terminal quickstart.

Marks: **[verified]** primary source fetched · **[secondary]** search results or summaries ·
**[prior]** from the researcher's prior knowledge. Re-check anything not verified before
citing it publicly.

---

## 1. How strong agent repos are organised

| Practice | Why | Source |
|---|---|---|
| Demo (GIF / video) and a results table above the fold | Reviewers skim; numbers + a visible demo separate a project from a tutorial | convention; https://github.com/google/adk-samples (per-recipe READMEs, recipe checklist) |
| Follow the platform's own layout | Shows platform fluency. Google's scaffolder is now **google/agents-cli** (scaffold → eval → deploy → observe) | https://google.github.io/agents-cli/ [secondary: exact layout not retrieved] |
| ADRs (Nygard format) for non-obvious choices | Hiring managers look for reasoning (receipts, topology, model choice) | https://adr.github.io/ |
| **System card** (intended / out-of-scope use, evals, limitations) | Established documentation form (model cards, Mitchell et al. 2019). Do **not** call it "agent card" — that is A2A's JSON capability manifest | https://arxiv.org/abs/1810.03993 [prior for A2A naming] |
| Deliberate tool design | Few consolidated tools, namespacing, high-signal responses, actionable errors, strict schemas, evaluated on realistic multi-call tasks | https://www.anthropic.com/engineering/writing-tools-for-agents [verified] |

**Industry vs amateur:** one-command reproduction, scorecard with CIs, cost per query, threat
model, ADRs, honest limitations, CI badges — vs a feature list without numbers, screenshots
instead of evals, marketing language ("AI health coach"), no failure analysis.

## 2. Agent evaluation

| Practice | Why | Source |
|---|---|---|
| **Error analysis before metrics**: read and annotate real traces (≥30, toward ~100) until failures saturate; build a failure taxonomy | "The most important activity in evals"; tests then target real failures | https://hamel.dev/blog/posts/evals-faq/ [verified] |
| **Binary pass/fail judges, one per failure mode**, validated on human labels; report TPR/TNR on a held-out split; code checks for anything objective | Likert scores are inconsistent; unvalidated judges are a red flag | same [verified] |
| **Capability evals vs regression evals**: capability starts at a low pass rate; regression sits near 100% and gates CI. Several trials per task (**pass@k / pass^k**); start with 20–50 tasks from real failures; balanced positive/negative cases; clean environment per trial; grade outcomes not paths; judges may answer "unknown"; read transcripts | Anthropic's agent-eval guidance | https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents (2026-01-09) [verified] |
| **ADK native metrics** (names reviewers recognise): `tool_trajectory_avg_score`, `final_response_match_v2`, `rubric_based_tool_use_quality_v1`, `hallucinations_v1`, `safety_v1`, `multi_turn_task_success_v1`, user simulation; efficiency metrics reported not gated (`tool_call_count_v1`, `token_usage_v1`, `invocation_duration_v1`); `*.evalset.json` via `adk eval` or pytest `AgentEvaluator`; `adk conformance` for recorded baselines | Use the platform's evaluation vocabulary | https://adk.dev/evaluate/ [verified] |
| Evaluate tool selection, arguments and handoffs; control judge length bias; prefer pass/fail or pairwise; "multi-agent should be driven by your evals" | OpenAI eval guidance | https://developers.openai.com/api/docs/guides/evaluation-best-practices [verified] |
| Statistics: CIs, clustered SEs when items share a source, **paired** comparisons on the same items, power analysis (~500 items to detect ~9 points) | Small eval sets detect only large differences — say so | https://arxiv.org/abs/2411.00640 [partly verified: abstract] |

**Industry vs amateur:** failure taxonomy from real traces, judge–human agreement table,
single vs multi as a paired test with bootstrap CIs, cost and latency per task, CI regression
gate — vs "helpfulness 4.2/5", unvalidated judge, one run per case, no negative cases.

## 3. Observability

- **OpenTelemetry GenAI semantic conventions are still "Development"** (moved to
  https://github.com/open-telemetry/semantic-conventions-genai in 2026). Agent spans
  (`invoke_agent`, `execute_tool`) exist. Pin the version and say it is Development. [secondary]
- **ADK → Cloud Trace** via `telemetry.googleapis.com`; content capture only with
  `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`; Google suggests
  `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false` to keep PII out.
  https://cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk
- **MCP 2026-07-28** documents W3C trace-context propagation in `_meta` → end-to-end traces
  agent → MCP. https://modelcontextprotocol.io/specification/2026-07-28/changelog [verified]
- Log: model, tokens, latency, tool name, args hash, **receipt id**, cost, eval verdicts;
  content off by default. Phoenix or Langfuse as a free local OTLP viewer. [prior]

**Industry vs amateur:** trace screenshot, receipts linked to span ids, content capture off
with a written rationale, evals over stored traces — vs print logs or full health prompts sent
to a third-party SaaS.

## 4. Security

- **OWASP Top 10 for LLM Applications 2025** (LLM01 prompt injection, LLM02 sensitive
  information disclosure, LLM05 improper output handling, LLM06 excessive agency, LLM07 system
  prompt leakage, LLM10 unbounded consumption, …) https://genai.owasp.org/llm-top-10/ [prior]
- **OWASP Top 10 for Agentic Applications 2026** (published 2025-12-09): ASI01 agent goal
  hijack, ASI02 tool misuse, ASI03 identity & privilege abuse, ASI04 supply chain, ASI05
  unexpected code execution, ASI06 memory & context poisoning, ASI07 insecure inter-agent
  comms, ASI08 cascading failures, ASI09 human-agent trust exploitation, ASI10 rogue agents.
  https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
  [secondary: exact titles unverified]
- **Lethal trifecta**: private data + untrusted content + external communication; cut at
  least one leg and document which. https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/
  [verified]
- **Design patterns over filters**: action-selector, plan-then-execute, dual-LLM,
  code-then-execute (https://arxiv.org/abs/2506.08837); CaMeL capabilities/provenance
  (https://arxiv.org/abs/2503.18813). Our untrusted-text wrapping, read-only SQL and receipts
  fit this framing.
- **Sandbox with a kernel boundary**: gVisor, Firecracker, E2B. **Cloud Run sandboxes**
  (public preview July 2026: no env/metadata access, no egress by default, ephemeral FS; an
  ADK `CloudRunSandboxCodeExecutor` expected) — a candidate second sandbox backend.
  https://cloud.google.com/blog/topics/developers-practitioners/google-cloud-run-sandboxes-are-in-public-preview
  [secondary: press-sourced]
- **Red-team reporting the AgentDojo way**: utility (benign), utility under attack, **attack
  success rate**, attack types and counts; add adaptive attacks.
  https://github.com/ethz-spylab/agentdojo; tools promptfoo, garak, PyRIT [prior]

**Industry vs amateur:** `THREAT_MODEL.md` with trifecta analysis and OWASP mapping,
red-team suite in CI with ASR and CIs, sandbox-escape tests — vs "the system prompt tells it
not to…".

## 5. Health-specific responsible AI

- **FDA General Wellness guidance (revised 2026-01-06)**: no disease/diagnosis claims,
  non-invasive, low risk. Cite FDA's own page.
  https://cov.com/en/news-and-insights/insights/2026/01/fda-issues-revised-guidance-on-general-wellness-products
  [secondary]
- **EU AI Act Art. 50** AI-interaction disclosure applies from 2026-08-02 (the Digital
  Omnibus delayed high-risk rules, not this).
  https://www.ropesgray.com/en/insights/viewpoints/102nfqm/you-talkin-to-me-operationalising-the-eu-ai-acts-transparency-obligations
  [secondary]
- **How Google evaluated**: PHIA (Nature Communications 2026; arXiv 2406.06464) — 84%
  objective numeric accuracy with code generation, plus 650 h of expert rating. PHA
  (arXiv 2508.20148) — 10 tasks, 7,000+ annotations; data-science agent code scored against
  data-scientist unit tests (75.5% vs 58.4% first-pass); multi vs single-agent by preference;
  cost reported (~6.5 LLM calls per query). https://research.google/blog/the-anatomy-of-a-personal-health-agent/
- **Our analogue**: numeric accuracy against receipted ground truth, code unit tests,
  owner-as-expert rubric ratings; red-flag escalation cases (chest pain → seek care),
  diagnosis-refusal cases, and **over-refusal** cases.

**Industry vs amateur:** a short "wellness only, not medical advice, n=1" line, a system card
with out-of-scope uses, safety evals with pass rates — vs disclaimer walls or no scope at all.

## 6. Forecast evaluation (the second act)

**Must have**
- Strictly proper scoring rules: **RPS** (ordinal 1–10), **log score**; Brier for binary
  events; CRPS if continuous. Gneiting & Raftery 2007, https://doi.org/10.1198/016214506000001437
- **Skill scores** vs named baselines (climatology, persistence): SS = 1 − S/S_ref, on a
  strictly out-of-sample, rolling-origin basis (our pre-registration + hash chain covers this).
  https://otexts.com/fpp3/tscv.html
- **Calibration and sharpness**: reliability diagrams with consistency bands; CORP
  (Dimitriadis et al., PNAS 2021, https://doi.org/10.1073/pnas.2016191118); "maximise
  sharpness subject to calibration" (Gneiting, Balabdaoui & Raftery 2007). [prior]
- **Paired comparison of forecasters**: Diebold–Mariano with the Harvey–Leybourne–Newbold
  small-sample correction, or block bootstrap (autocorrelation); multiplicity correction across
  7 forecasters, or one pre-registered primary comparison (ours). [prior]

**Nice to have**
- Discrimination for threshold events: ROC AUC (e.g. "energy ≤ 3").
- Pre-registration in OSF style (https://osf.io/prereg/) or the in-repo equivalent (ours).
- **TRIPOD+AI** as a reporting checklist (BMJ 2024;385:e078378,
  https://www.bmj.com/content/385/bmj-2023-078378). **CENT 2015** is for N-of-1
  *intervention* trials — borrow single-participant reporting ideas only. SPIRIT/CONSORT do
  not apply (nothing is randomised).

**Honest small-n phrasing:** lead with CIs, not p-values — "no evidence of skill over
persistence at n = X days (ΔRPS 95% CI [a, b])", state the minimum detectable effect, call the
results exploratory for one person.

**Industry vs amateur:** leaderboard with skill and CIs, reliability diagrams, frozen
pre-registration hash, null results published — vs accuracy/MAE on probabilities, in-sample
tuning, no baselines.

## 7. MCP server (Phase 5)

- Target **spec 2026-07-28**: stateless (no `initialize` handshake, no `Mcp-Session-Id`),
  required `server/discover` and `resultType`, `ttlMs` / `cacheScope` on list results,
  deterministic `tools/list` order, OTel propagation via `_meta`; Roots, Sampling, Logging and
  Dynamic Client Registration deprecated in favour of Client ID Metadata Documents.
  https://modelcontextprotocol.io/specification/2026-07-28/changelog [verified]
- **Read-only by design**: query and receipt tools only, `readOnlyHint` / `idempotentHint`
  annotations [prior: names], strict input/output schemas with `structuredContent`, untrusted
  text labelled.
- **Transport/auth**: stdio for local (recommended); remote = OAuth 2.1 with audience-bound
  tokens, PKCE S256, **no token passthrough**, minimal scopes with incremental elevation,
  validate `iss` (RFC 9207).
  https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices [verified]
- **Present with evidence**: MCP Inspector screenshot, Claude Desktop / Gemini CLI demo,
  security section mapped to the spec's attack list, eval tasks run through MCP.

**Industry vs amateur:** current spec, read-only annotations, stdio default, threat-model
section, contract tests — vs a one-to-one wrapper per SQL table, raw `execute_sql`, an old
spec version.

---

## Recommended organisation (adopted direction)

### README — agent first, forecasting second, web UI as the front door

The README is completed in Phase 8, once the Phase 7 web app exists. Until then it carries the
same order with what is live.

1. **One line + hero GIF of the web app** (Phase 7): ask a question in the browser, the answer
   streams with tool steps, open a receipt and re-run it. Scope line: personal portfolio,
   wellness only, not medical advice, n = 1.
2. **See it live**: the synthetic-data demo (one command, `docker compose up`, Phase 6/7) and
   the launch video (Phase 8). The owner's real data is never in the demo. Video tool: the
   installed **/brag** plugin (turns the project's web front end into a short launch video
   with music, motion and share copy, built with Hyperframes from the project code) is a
   candidate alongside the spec's "Claude motion"; compare both on the Phase 7 web app in
   Phase 8 and keep the better one (owner, 2026-10-25).
3. **Scorecard**: task success, numeric accuracy vs receipts, tool-trajectory score,
   groundedness, refusal and red-flag escalation correctness, over-refusal, red-team ASR and
   utility under attack, p50/p95 latency, $ per query — each with a 95% CI, n and the commit
   measured.
4. **Architecture**: diagram (web → AG-UI → ADK workflow → tools / sandbox / guarded SQL /
   memory; nightly investigator; forecast ledger) and the ADRs.
5. **How it is evaluated**: error-analysis taxonomy, judge–human TPR/TNR, CI gate, single vs
   multi as a paired result.
6. **Security**: trifecta analysis, OWASP LLM + Agentic mapping, sandbox, `THREAT_MODEL.md`.
7. **Second act — the forecasting experiment**: pre-registration, seven forecasters, RPS/log
   skill vs climatology and persistence with CIs, reliability diagram, 6 vs 7, honest
   interpretation; link to the public scoreboard and hash log.
8. **Observability**: trace screenshot, privacy defaults.
9. **MCP server**: what it exposes, copy-paste config.
10. **Run it yourself**: terminal (`cha ask`, `cha receipt`), local web app, the cloud slice
    (Terraform).
11. **Cost**: monthly breakdown under $1 and the levers.
12. **Limitations and responsible use**, roadmap, licence, citation.

### docs/ structure

```
docs/
  architecture.md
  system-card.md            intended / out-of-scope use, evals, limitations, health framing
  threat-model.md           trifecta, OWASP LLM / ASI mapping, sandbox, red-team results
  adr/                      0001 workflow shape (exists), receipts, sandbox, topology, content-capture-off, ...
  evals/
    methodology.md          error analysis → taxonomy → graders; statistics plan
    failure-taxonomy.md
    judge-calibration.md    labels, TPR/TNR, splits
    results/<date>-<sha>.md
  forecasting/
    preregistration.md      → docs/ledger/analysis-plan.md (frozen; never edited)
    protocol.md             scoring rules, baselines, rolling origin, DM / bootstrap
    results.md              with a TRIPOD+AI-style checklist appendix
  observability.md
  mcp.md
  runbook (infra/README.md), cost.md
evals/                      evalsets (*.evalset.json), red-team cases, judge prompts
```

### Phase 4 / 5 deliverables, in order of credibility per dollar

1. **Error analysis**: run the agent on a varied question set (synthetic data, plus owner-only
   real-data runs), the owner labels ~100 transcripts pass/fail → failure taxonomy → grow to
   ~200 cases (positive and negative, in and out of scope, red-flag escalation, over-refusal).
2. **Deterministic graders first**: numeric match vs receipts, tool-trajectory checks, refusal
   checks; ADK evalset format and `adk eval` / `AgentEvaluator`.
3. **Binary LLM judges** only for the remaining interpretive failure modes; calibrated on owner
   labels; TPR/TNR on a held-out split.
4. **CI gate**: 30–50 regression cases per PR; full suite nightly or on demand (synthetic data,
   free-tier key, judge caching).
5. **Statistics**: bootstrap CIs, paired single vs multi, pass^k on a subset.
6. **Red-team suite** (journal injections, SQL, sandbox escapes) reporting ASR and utility under
   attack; `THREAT_MODEL.md` with the OWASP mapping.
7. **OpenTelemetry → Cloud Trace** (pinned semconv, content off, receipt ids on spans; free
   tier).
8. **Forecasting results page**: skill with CIs, reliability diagrams, paired tests, frozen
   pre-registration linked.
9. **System card, ADRs, README re-order** (agent first).
10. **Phase 5 MCP server**: read-only, stdio-first, spec 2026-07-28; Inspector screenshot; evals
    through MCP; remote OAuth optional (documented if skipped).

Open decision for the owner (raised 2026-10-24): labelling ~100 transcripts pass/fail to ground
the failure taxonomy and the judge.

### Not verified (re-check before citing)

Exact OWASP ASI titles; agents-cli generated layout; OTel GenAI release/stability details;
Cloud Run sandbox specifics; FDA guidance text (law-firm summaries only); paired-SE formulas in
Miller's paper; Phoenix/Langfuse, AgentDojo, MCP annotation names, DM/HLN and CORP details
(prior knowledge).
