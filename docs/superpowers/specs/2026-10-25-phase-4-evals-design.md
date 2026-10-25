# Phase 4 — Evals, red-team and tracing: design

**Status:** Draft for owner review, 2026-10-25
**Parent spec:** `docs/superpowers/specs/2026-10-20-calibrated-health-agent-design.md` (§6.7, §6.8, §6.9, Phase 4 row)
**Research:** `docs/research/09-industry-practice-2026.md` (the practices and sources this design follows)
**Builds on:** Phase 3 (`docs/superpowers/specs/2026-10-23-phase-3-agent-core-design.md`), live since 2026-10-24

Marks: **[owner]** decided by the owner in conversation · **[call]** decided by Claude, owner to
check · **[builder]** left to whoever builds it.

---

## 1. Intent

Prove, with numbers a reviewer trusts, how good the agent is, and catch any change that makes
it worse. The project is a **personal portfolio**: it never claims to be an alternative to any
commercial service **[owner]**. The **agent answering questions is the front door; the
forecasting experiment is the second act and its evidence**, and both are presented to industry
standard **[owner]**.

Phase 4 follows the way practitioner teams build evals in 2025–2026 **[owner]** (research 09):
read real transcripts first, turn the failures you see into tests, grade objectively where you
can, validate any AI judge against a human, report intervals, gate CI on regressions, red-team
with a recognised vocabulary, and trace every run.

### Exit check (parent spec)

A deliberately regressed prompt fails the PR gate.

## 2. Goals, non-goals, anti-goals

**Goals**

| # | Goal | Done when |
|---|---|---|
| E1 | Error analysis | The owner has labelled ~100 agent transcripts pass/fail with a note on the review page; the notes are grouped into a failure taxonomy the owner confirms (`docs/evals/failure-taxonomy.md`) |
| E2 | Eval suites | ~200 cases in ADK evalset format under `evals/`, split into **regression** (must stay ~100%, gates CI) and **capability** (starts lower, shows progress), covering numeric accuracy, tool use, gap admission, refusal and red-flag escalation, over-refusal, and multi-turn |
| E3 | Graders | Code graders for everything objective (numbers against fixture truth and receipts, tool trajectory, refusal markers, blinded-table access); **binary LLM judges** only for the interpretive failure modes left over |
| E4 | Judge calibration | Each judge measured against held-out owner labels; TPR and TNR published (`docs/evals/judge-calibration.md`) |
| E5 | Statistics | Pass rates with Wilson 95% intervals and n; **paired** single vs multi comparison (McNemar + bootstrap interval); pass^k (k = 3) on a subset; stated minimum detectable difference |
| E6 | CI gate | GitHub Actions runs the regression suite on every PR on synthetic data; any must-pass failure, any regression vs `main` beyond the noise band, or any `NOT_EVALUATED` fails the PR |
| E7 | Red team | Injection (journal notes, device names, sandbox output), SQL abuse, sandbox escape and over-spend cases; utility, utility under attack and attack success rate (AgentDojo-style); `docs/threat-model.md` with the lethal-trifecta analysis and OWASP LLM 2025 + Agentic 2026 mapping |
| E8 | Tracing | OpenTelemetry GenAI spans (pinned semconv version, marked "Development") to Phoenix locally and Cloud Trace in the job; message content off in the cloud; receipt ids and cost on spans; a failure found in traces becomes a test case |
| E9 | Forecasting results page | `docs/forecasting/results.md`: skill with intervals, reliability diagrams, paired forecaster comparisons (Diebold–Mariano / block bootstrap), 6 vs 7, honest small-n wording, TRIPOD+AI-style checklist appendix; regenerated from the database by a command |
| E10 | Scorecard + docs | `cha eval report` writes `docs/evals/results/<date>-<sha>.md` and the README scorecard table; `docs/system-card.md`; ADRs for the Phase 3–4 choices; README re-ordered agent-first |

**Non-goals (this phase):** the web app (Phase 7); MCP (Phase 5); production online evaluation
on other users (there are none); fine-tuning; a paid eval SaaS.

**Anti-goals — failure even if it runs**

- Real health data in CI, in committed fixtures, in a trace that leaves the owner's machine or
  GCP project, or in any published artifact other than aggregates.
- An LLM judge whose agreement with the owner was never measured, used as if it were.
- A scorecard number without n and an interval, or tuned on the cases it reports.
- Single vs multi declared a winner without a paired test, or from a difference the test cannot
  detect.
- Eval or red-team runs that push total cloud spend over **$1/month** **[owner]**.
- Weakening a guard (sandbox, SQL authorizer, blinding) to make a test pass.

## 3. Constraints

- **Budget under $1/month** **[owner]**. CI and synthetic runs use a **free-tier Gemini API key**
  (allowed for synthetic data only, parent spec §5). Real-data runs are owner-triggered, on the
  laptop, and costed before they start; only aggregates leave the machine.
- **Synthetic data in CI** comes from `health_agents.smoke.build_fixture` (extended in this
  phase). Fixture truth is computed from the fixture itself.
- **Owner time:** ~100 labels over a few days on a click-through page **[owner]**, plus
  confirming the taxonomy.
- Phase 3 code is the system under test; its guards are not changed to pass tests.
- Windows dev, Linux CI and container.

## 4. The shape

```
 questions (dimensions × personas) ─► run agent (single & multi, k trials) ─► transcripts (JSONL)
                                                                                   │
                         owner labels on the review page (pass/fail + note) ◄──────┘
                                       │
              open coding → axial coding → failure taxonomy (owner confirms)
                                       │
          eval cases (ADK evalsets) ─► graders: code first, binary judges second
                                       │                     │
                     regression suite → CI gate      judges calibrated on held-out labels
                     capability suite → nightly / on demand
                                       │
                  statistics → scorecard (results/<date>-<sha>.md, README table)
   red-team suite → ASR / utility under attack → threat model
   OTel spans → Phoenix (local) / Cloud Trace (job)        forecasting results page (ledger)
```

### 4.1 Transcript generation (E1, E2)

- **Question generator** **[call]**: a fixed set of dimensions crossed into concrete questions:
  intent (number, trend, comparison, explanation, coaching, out-of-scope, medical), time window,
  data state (complete, gappy, missing metric, no journal), and persona (curious, terse,
  anxious, adversarial). An LLM drafts candidates from the grid; the builder keeps realistic
  ones. Stored in `evals/questions/*.yaml` with their dimension tags.
- **Runner** **[call]**: `cha eval run --set <name> [--topology single|multi] [--trials k]`
  runs each question through the Phase 3 `Session` on the synthetic fixture (or, with
  `--real`, on the owner's database, laptop only) and writes one JSONL transcript per run:
  question, final answer, tool calls with arguments and outputs, receipt ids, tokens, cost,
  latency, topology, commit, fixture hash. Synthetic transcripts may be committed; real ones
  stay in `data/evals/` (git-ignored).
- **Batch size for labelling:** ~120 runs (about 100 synthetic across both topologies, plus a
  few real-data runs the owner chooses), so ~100 labels survive de-duplication.

### 4.2 Review page (E1)

`cha review <transcripts.jsonl>` starts a local page (Python standard library HTTP server,
bound to 127.0.0.1) showing one transcript at a time: question, answer, collapsible tool calls
and receipts, and **Pass / Fail** buttons with a short note box and keyboard shortcuts. Labels
append to `<transcripts>.labels.jsonl` (owner, timestamp, verdict, note). Labels on real-data
transcripts stay local. **[call]** standard library, no new dependency; a trace tool's
annotation queue (Phoenix) is the alternative.

### 4.3 Failure taxonomy (E1)

Open coding is the owner's free-text notes. The builder groups them (axial coding) into
categories with counts and examples, and the owner confirms or edits the list. Each category
becomes either a code check or a binary judge, and seeds cases in the suites.
`docs/evals/failure-taxonomy.md` records categories, counts, examples and the grader that
covers each.

### 4.4 Suites (E2)

ADK `*.evalset.json` under `evals/`, run through `AgentEvaluator` from pytest (and `adk eval`
for ad-hoc runs) **[call]** so the metric names are ADK's own:

| Suite | Size (target) | Content | Cadence |
|---|---|---|---|
| `regression` | 40–50 | must-pass behaviours drawn from the taxonomy, numeric accuracy on the fixture, blinding, refusal, red-flag escalation | every PR (CI gate) |
| `capability` | ~80 | harder multi-step analysis, multi-turn, ambiguous questions, over-refusal traps | nightly / on demand |
| `safety` | ~30 | diagnosis requests, dosing, emergencies (escalate), over-claiming, over-refusal | every PR (subset) / nightly |
| `redteam` | ~40 | §4.7 | SQL and sandbox cases every PR (no LLM needed); injection nightly |
| `ablation` | ~60 numeric | §4.6 | milestones, on demand |

Positive and negative cases are balanced; each case names its taxonomy category.

### 4.5 Graders (E3, E4)

- **Code graders first** (`health_eval.graders`) **[call]**: numeric match against fixture
  truth at the answer's precision (reusing `verify` logic), every number backed by a receipt that
  re-runs, expected tools called (ADK `tool_trajectory_avg_score` where it fits), no read of a
  blinded table, refusal and escalation markers, `unverified:` footer present or absent as
  expected, latency and cost recorded (reported, never gated).
- **Binary LLM judges** only for categories code cannot decide (e.g. "gives a diagnosis",
  "answers the question asked", "admits a gap"), one prompt per category with an "unknown"
  option, run on Flash-Lite through the free-tier key on synthetic transcripts.
- **Calibration**: owner labels split into train (to tune the judge prompt), dev and a held-out
  test split **[call: 40/20/40]**; TPR and TNR on the test split with Wilson intervals; a judge
  below 0.8 on either is reported but not used to gate.

### 4.6 Statistics and the ablation (E5)

- Wilson 95% intervals for every pass rate, with n.
- **Single vs multi:** paired on the same cases, McNemar test plus a paired bootstrap interval
  on the difference; the minimum detectable difference at this n is stated next to the result.
- **pass^k** with k = 3 on the regression suite (does it pass every time?).
- **Ablation (PHIA-style)** on the synthetic numeric set: model only (no tools) / tools without
  code / tools + code / single / multi. Free-tier key, synthetic data. A real-data ablation is
  optional, owner-triggered, and costed first **[call: default off]**.

### 4.7 Red team (E7)

- **Attacks**: prompt injection in journal notes, device names and sandbox output (direct,
  obfuscated, multi-step); goal hijack via memory (`save_fact` must still ask); SQL abuse (blinded
  tables, PRAGMA, recursive CTE bombs, untrusted columns); sandbox escapes (the Phase 3 probes
  plus new ones); unbounded consumption (cap behaviour).
- **Reporting (AgentDojo-style)**: utility on benign tasks, utility under attack, attack success
  rate, per attack family, with n and intervals.
- **`docs/threat-model.md`**: assets, the lethal-trifecta legs and which one each control cuts,
  OWASP LLM Top 10 (2025) and Agentic Top 10 (2026) mapping, residual risks (e.g. the Windows
  sandbox has no memory limit).

### 4.8 Tracing (E8)

- OpenTelemetry via ADK's built-in instrumentation; GenAI semantic conventions pinned and marked
  "Development".
- **Local:** Phoenix (OTLP) for the owner's runs and for eval transcripts.
- **Job:** Cloud Trace via `telemetry.googleapis.com`, with
  `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false` and content capture off; the job's service
  account gets the trace-writer role in Terraform. Free tier (2.5M spans/month) is far above use.
- Span attributes: model, tokens, cost, latency, tool name, args hash, receipt id, eval verdict.
- `docs/observability.md` documents what is and is not captured, and why.

### 4.9 CI gate (E6)

- New GitHub Actions job `evals` on pull requests: builds the fixture, runs the `regression`
  suite and the no-LLM red-team cases with the free-tier key from a repository secret, compares
  against the last `main` result stored as an artifact, and fails on: any must-pass failure, a
  drop beyond the noise band (from pass^k on `main`), or `NOT_EVALUATED`.
- Judge outputs are cached by (judge version, transcript hash) to save quota.
- **Exit check:** a PR that deliberately weakens a prompt (e.g. removes the receipt rule) is
  shown failing the gate; recorded in the results docs.

### 4.10 Forecasting results page (E9)

`cha-ledger report` (new command) reads settled data and writes `docs/forecasting/results.md`
and figures: skill vs climatology and persistence with block-bootstrap intervals, reliability
diagrams (consistency bands), Diebold–Mariano (Harvey–Leybourne–Newbold correction) for the
pre-registered comparisons, 6 vs 7, sharpness, and the honest-small-n sentence ("no evidence of
skill at n = X; ΔRPS 95% CI [a, b]"). Published figures are aggregates only and follow the
public-board rules (rounded, refreshed every 7 settled days). `docs/forecasting/protocol.md`
links the frozen pre-registration (`docs/ledger/analysis-plan.md`, never edited).

### 4.11 Scorecard, system card, README (E10)

- `cha eval report` turns the latest runs into `docs/evals/results/<date>-<sha>.md` and the
  README scorecard: task success, numeric accuracy, tool-trajectory score, refusal and
  escalation correctness, over-refusal, ASR and utility under attack, p50/p95 latency, $ per
  question, each with n, interval and commit.
- `docs/system-card.md`: intended use (one person's wellness questions about their own data),
  out-of-scope uses, evaluation summary, limitations, health framing (FDA general wellness,
  EU AI Act Art. 50 disclosure).
- ADRs: receipts, sandbox, topology default, content capture off, eval methodology.
- README re-ordered per research 09: agent first, scorecard, architecture, evaluation, security,
  then the forecasting experiment.

## 5. Package and files

New workspace package **`health_eval`** **[call]** (parent spec layout): `questions.py`,
`runner.py`, `review.py` (the page), `graders.py`, `judges.py`, `stats.py`, `report.py`.
`cha eval …` and `cha review` subcommands are added to the existing CLI. Eval data under
`evals/` (sets, questions, judge prompts, synthetic transcripts and labels), docs under
`docs/evals/`, `docs/forecasting/`, `docs/threat-model.md`, `docs/system-card.md`,
`docs/observability.md`.

## 6. Cost (estimates; checked before real runs)

| Item | Monthly |
|---|---|
| CI evals on synthetic data | $0 (free-tier key) |
| Nightly / on-demand synthetic suites, ablation | $0 (free-tier key; within its daily limits) |
| Real-data labelling batch (~20 runs, once) | ≈ $0.30 one-off, inside the chat cap |
| Optional real-data ablation | costed first; off by default |
| Cloud Trace (job spans) | $0 (free tier) |

Total new cloud spend stays ≈ $0; the existing $0.30 chat cap still bounds real-data runs.

## 7. Owner actions this phase needs

1. Label ~100 transcripts on the review page and confirm the taxonomy **[owner]**.
2. Create a **free-tier Gemini API key** (Google AI Studio) and add it as the GitHub repository
   secret `GEMINI_API_KEY` — synthetic data only.
3. Approve the Terraform change for the trace-writer role and the job image redeploy.

## 8. Left to the builder

Exact question wording within the grid; the de-duplication rule for transcripts; judge prompt
wording; the noise-band formula; figure styling; how ADK metrics and custom graders are combined
in one report.

## 9. Builder-check resolutions (2026-10-25) [call]

1. **CI backend without changing Phase 3 code.** `vertex.configure()` only sets defaults
   (`os.environ.setdefault`), so CI sets `GOOGLE_GENAI_USE_VERTEXAI=false` and
   `GOOGLE_API_KEY=${{ secrets.GEMINI_API_KEY }}` and ADK uses the AI Studio key. The model stays
   `Settings.model_default`. The first plan task verifies on the free tier that the model is
   served and records its RPM/RPD limits; the regression suite is sized to fit one PR job within
   them. If quota is short, the PR gate runs the must-pass subset with k = 1 and the nightly job
   runs the rest with k = 3 — the gate shrinks, the nightly coverage does not.
2. **Flakiness.** A must-pass case fails the gate only if it fails on a retry too (one automatic
   retry, so k ≤ 2 per case on PRs). The "last `main`" baseline is produced by the same job on
   pushes to `main` (and nightly) and stored as an artifact; the noise band comes from the nightly
   pass^3. The repo is solo with no fork PRs, so secrets are available to PR runs.
3. **What gates.** Code graders gate from day one. A judge gates only after its held-out TPR and
   TNR are both ≥ 0.8; until then its results are reported, not gating.
4. **Source of truth.** The runner's JSONL transcripts are the source of truth for grading. Cases
   live in ADK evalsets (question, expected tools, expected behaviour, and fixture truth in the
   case's metadata), and ADK metrics (`tool_trajectory_avg_score`, `hallucinations_v1`,
   `safety_v1`) run where they fit; custom graders read the same transcripts. One report merges
   both.
5. **Labels and splits.** Transcripts the owner labels are kept separate from the cases reported
   on the scorecard (labelled runs feed the taxonomy and judge calibration; reported numbers come
   from fresh runs of the suites). With ~100 labels, the judge test split is ~40 and its TPR/TNR
   intervals are wide; that is reported as such, and more labels can be added over time. The plan
   is staged: graders, red-team, tracing, the forecasting page and the CI skeleton proceed before
   labels exist; judges and the taxonomy follow the labelling.
6. **Forecasting page.** It follows the comparisons in `docs/ledger/analysis-plan.md` (primary:
   energy, forecaster 6 vs persistence; secondary as listed). Below 10 paired days it renders the
   structure with the real n and "not yet" in place of intervals — that counts as done for this
   phase; it fills in as days settle.
7. **Tracing deploy** is its own owner-approved task (Terraform trace-writer role + image
   redeploy) and does not block the exit check.
8. **Linux CI.** The sandbox and SQL red-team cases run on ubuntu runners with the Linux
   resource limits active (the `linux_only` tests run there); expected outcomes are the same
   (refused or killed), with the memory and CPU limits additionally enforced.
