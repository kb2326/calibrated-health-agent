# Calibrated Health Agent — Design

**Status:** Approved by owner 2026-10-20
**Date:** 2026-10-20
**Owner:** Karthick (GitHub `kb2326`)
**Supersedes:** the 2026-10-19 portfolio-revamp spec and plan (deleted)
**Evidence base:** `research_notes/2026-10-20-deep/` — 00 synthesis, 01 hiring signals,
02 frameworks/protocols/memory, 03 GCP architecture, 04 personal-health-AI frontier,
05 evals/observability/safety, 06 app/data/publishing, 07 pioneers, 08 fact-check.
**Architecture:** `docs/architecture.md` (end-to-end how, with diagrams).
**Living overview:** the "Calibrated Health Agent — project doc" artifact (vision → output, kept current).

Marks used below: **[owner]** = decided by the owner in conversation; **[call]** =
decided by Claude, owner to check; **[builder]** = deliberately left to whoever builds it.

---

## 1. Intent

Rebuild this repository into a portfolio-grade agentic AI system that a hiring
reviewer can understand, watch, and trust in under two minutes — and that teaches the owner
the skills the late-2026 market asks for by building them for real. **[owner]**

The system runs on the owner's **real** Google Health API data. **[owner]**

### The one-line pitch

> A personal health agent that **keeps score**: it forecasts how you'll feel
> tomorrow, grades itself against simple baselines on your real data, shows a code
> receipt for every number, and publishes its evals — including where it loses.

### Why this shape (from the research)

- Plain LLMs answer personal-health numeric questions correctly ~22% of the time;
  an agentic code pipeline reaches 84% (PHIA, *Nature Communications* 17:1143, 2026).
  Computing, not narrating, is the job.
- The data-scientist / domain-expert / coach topology is Google's own published and
  shipped design, and ≥4 read-only Google Health MCP servers already exist. Rebuilding
  either on trendier tools is not distinctive.
- No product or paper publishes a **scored, per-person track record** of its own
  predictions against a naive baseline. That is the gap this project fills.
- Hiring evidence: "ship, measure, defend". Evals are the fastest-rising skill; MCP
  (#1) and RAG (#2) top agentic postings; "multi-agent for its own sake" and "can't
  estimate inference cost" are named red flags; a live URL and recorded walkthrough
  convert.

### Who it serves

1. **The owner** — a private, grounded view of their own health data that gets better
   as they journal.
2. **A reviewer** — README, video, LinkedIn post and Medium article show real data
   handled honestly, measured quality with baselines, and production-grade GCP
   infrastructure as code. There is **no paid public demo** **[owner]**.

---

## 2. Goals

| # | Goal | Done when |
|---|------|-----------|
| G1 | **Forecast ledger** on real data | Every day, probabilistic forecasts of mood, energy and soreness are locked before the journal entry, scored with proper scoring rules against baselines, and shown with calibration and real n. |
| G1b | **An agent that learns from its own misses** | After each scored day, an investigator agent examines the biggest misses with code, writes hypotheses with receipts into memory, and a forecaster that reads those notes is scored against an identical one that doesn't — answering whether the agent's self-reflection improves its forecasts. |
| G2 | **Receipts** for every number | Any numeric claim the agent makes links to the code/query that produced it and re-runs to the same value. |
| G3 | **Honest statistics** | Non-wear days are detected and excluded; baselines are robust; associations are detrended, carry CIs and multiple-test correction, and are labelled as associations. |
| G4 | **Measured agent quality** | Eval suites run in CI with a merge gate; the PHIA-style ablation and the single- vs multi-agent comparison are published with intervals; the LLM judge is calibrated against owner labels. |
| G5 | **Proven safety** | Prompt-injection via stored data, SQL abuse, and medical-boundary cases are red-teamed, with before/after attack-success rates mapped to OWASP Agentic IDs. |
| G6 | **Deployed on GCP for learning, near $0** | Terraform provisions everything; daily jobs run on Cloud Run jobs within free tiers; the owner service deploys behind IAP and scales to zero; CI deploys without keys; a full destroy-and-redeploy is demonstrated; total spend stays under $5/month. **[owner]** budget |
| G7 | **Portable** | A read-only MCP server works from Claude Desktop/Cursor via copy-paste config. |
| G8 | **Story told** | README written as a product spec, ADRs, a **LinkedIn post**, a **Medium article**, and a **motion video made with Claude ("Claude motion")**, all pointing to `github.com/kb2326`. **[owner]** |

## 3. Non-goals

- Multi-user SaaS: sign-up, billing, multi-tenancy, mobile apps.
- Writing to the Google Health API. The project stays read-only at every level.
- Beating commercial coaches on features.
- A LangGraph rewrite of the orchestration. **[call]**

## 4. Anti-goals — failure even if it runs

- Any diagnosis, disease name, or clinical instruction (FDA general-wellness boundary).
- Raw real health series in any public place — repo, demo, screenshots, traces, blog.
  Wearable data re-identifies at 86–100%.
- Fabricated or synthetic history presented as the owner's. The ledger shows real n.
- Numbers without baselines or without sample sizes.
- Multi-agent presented as better without the single-agent comparison.
- Dead links, or a README that doesn't work from a fresh clone.
- Spending beyond the budget, or anything that runs up cost while idle.
- Stack items present only as keywords (see §8 skip list).

---

## 5. Constraints

| Constraint | Detail |
|---|---|
| Data source | Google Health API v4 (successor to the Fitbit Web API, which shuts off 2026-10-30). Read-only scopes only. Verified live 2026-10-20. |
| Real data depth | About 7 months of history; recent wear is sparse; overnight wear has resumed **[owner]**; the journal has just started. The owner commits to daily journaling + overnight wear **[owner]**. |
| Data clock | The ledger's first calibration curve needs ≈30 journal days; credible at 60–90. Anything that delays daily journaling delays the headline. |
| OAuth | App is in "Testing" (refresh tokens expire after 7 days). Must be published "In Production" before scheduled sync; unverified apps are allowed (≤100 users). Add `profile.readonly` and `settings.readonly`. |
| Budget | **Under $5/month total** **[owner]**; target ≈ $1–2. Budget alerts at $2/$4, Cloud Run spend cap, quota limits on the paid Gemini key. GCP services stay inside free tiers (region must be a free-tier US region). Paid-tier Gemini only for anything touching **real** data (free-tier data is used to improve Google products); **synthetic-fixture** evals and CI may use a free-tier key. **[call]** |
| Cloud | Personal project **`artful-timing-506108-n8`** ("Google Health Agent", account karthickbalaje01@gmail.com) **[owner]**. It already holds the Health API OAuth client, has billing (My Billing Account 1) and the Health API, BigQuery, Storage, Trace and Logging enabled. |
| People | Solo owner + Claude as builder. |
| Dev machine | Windows 11; everything must also run in Linux containers / CI. |
| Licensing | Code Apache-2.0; synthetic dataset CC-BY-4.0. **[call]** |
| Regulatory | Wellness framing only; disclose AI interaction (EU AI Act transparency duty applies from Aug 2026); "not medical advice / not a medical device" disclaimer stack. |
| Model pricing | Gemini 3.6/3.8 Flash prices double 2027-01-01; model IDs live in config, never hard-coded. |

---

## 6. System design

### 6.1 Data substrate

- **SQLite remains the system of record**, held in GCS as the single source of truth (local
  writes pull first). It stores daily values and point/session raw data only and must stay
  under 50 MB; minute-level streams are never stored in it (monthly Parquet in GCS if ever
  needed). Existing schema and read-only guarantees carry over; DB is VACUUMed (today a few MB
  of data in a heavily over-allocated file). **[call]**
- **DuckDB** attaches SQLite for analytics; **Parquet** is the export format;
  **pandera** schemas check every pipeline output. **[call]**
- Sync expands from 11 to the useful readable types (adds at least respiratory rate,
  sleep temperature derivations, VO2 max, active zone minutes, daily HRV/SpO2 where
  available). Exact set **[builder]** after checking what the owner's device emits.
- Summed types come from `dataPoints.reconcile` / `dailyRollUp` so multiple sources never
  double-count; raw points keep their source. Add `pairedDevices`, profile and settings.
- One-time **full backfill** from the start of history; daily incremental after.
- Webhooks (signed, metadata-bearing POSTs) are a later optimisation, not required.

### 6.2 Data quality and wear awareness

- A day is **worn** or **not worn** per metric family by an explicit, documented rule
  (e.g. minimum heart-rate coverage hours; sleep present). Rule specifics **[builder]**,
  but it must be written down, tested, and surfaced in the UI.
- Non-worn days are excluded from baselines, anomalies, correlations and forecasts'
  inputs, and are reported as gaps — never silently imputed.

### 6.3 Honest statistics (replaces today's analyze/correlate/learn)

- **Baselines:** rolling robust statistics (median/MAD or equivalent) over worn days.
- **Anomalies:** robust z against the personal baseline; wellness wording only.
- **Associations:** detrended series, lag 0/1, confidence intervals, Benjamini–Hochberg
  correction across all tests in a run, minimum-n gates; always labelled "association".
- **Self-experiments (optional, later):** the agent may propose randomized ABAB blocks
  for a hypothesis; never claims causation from observational data.

### 6.4 The forecast ledger (centrepiece)

- **Targets:** journal fields mood, energy, soreness, each 1–10. **[call]** (existing fields)
- **Timing:** the journal for day D is logged in the evening of D. Forecasts for D may use
  data through the end of the sleep that ended on the morning of D. The lock is
  **event-triggered** when that sleep record arrives, with a **12:00 local deadline**
  (deadline locks record missing inputs). A journal entry submitted before the day's lock
  invalidates that day. **[call]**
- **Integrity:** locked forecasts **and imported outcomes** are append-only and
  hash-chained, written to a retention-locked GCS bucket, and each day's chain hash is
  pushed to a separate **public** repo `kb2326/cha-ledger-log` (date + hash only — no lock
  times or missing-input flags, which would reveal sleep/wear patterns) using a fine-grained
  token scoped to that repo and kept in Secret Manager. The first entry is the hash of a
  **pre-registered analysis plan** (forecaster definitions, primary endpoint, scoring
  windows). Starts with the first lock. **[call]**
- **Blinding (default on):** unmatured forecasts are hidden from every owner-facing surface
  (UI, chat, digest, MCP, memory) until scored, so they can't anchor the journal. **[call]**,
  owner to confirm (§10).
- **Output:** a full probability distribution over 1–10 per target (not a point).
- **Forecasters (competitors on one scoreboard):**
  1. Climatology — the owner's historical distribution (outside view).
  2. Persistence — yesterday's value with empirical spread.
  3. Seasonal-naive — same weekday.
  4. A statistical model on wearable features (choice **[builder]**: e.g. ordinal regression),
     including an **open readiness score** computed transparently from HRV, resting HR and
     sleep vs the personal baseline — the documented counterpart of the proprietary
     readiness/recovery scores the API does not expose.
  5. TimesFM via BigQuery `AI.FORECAST`.
  6. The Gemini agent as forecaster, given the same inputs (**no notes**).
  7. The same Gemini agent **plus its own investigation notes** (§6.6a) — identical inputs
     otherwise. Starts when the investigator lands (Phase 3); 6 vs 7 is a pre-registered
     secondary hypothesis.
- **Primary endpoint (pre-registered):** energy, RPS skill vs persistence, reported with
  paired block-bootstrap (or Diebold–Mariano) intervals. Everything else is secondary.
- **Scoring:** ranked probability score (ordinal), log score, and skill scores vs
  climatology and persistence; calibration via PIT histograms or ≤5 coarse bins (n is
  small); rolling-origin evaluation; adaptive conformal intervals where intervals are shown.
- **Forecaster details:** climatology starts from a stated weakly-informative prior until
  enough journal days exist; TimesFM's quantile output gets a defined mapping to a 1–10
  distribution, or TimesFM moves to the backtest panel if no defensible mapping exists on
  short, gappy series; the Gemini forecaster pins model version and temperature, and any
  model change is scored as a new forecaster.
- **Forecasters 1–6 lock from Phase 2; forecaster 7 from Phase 3** (BigQuery mirror and the Gemini endpoint move
  forward accordingly). The scoreboard counts **live locked** forecasts only; rolling-origin
  backtests appear in a separate labelled panel. The Gemini forecaster gets exactly the
  same feature snapshot as the statistical ones. **[call]**
- **Honesty rule:** the scoreboard is published as-is, including forecasters that lose
  to persistence. Real n is always displayed.
- The old `learn.py` per-signal weight loop is retired in favour of this ledger. **[call]**

### 6.5 Journal capture

Daily journaling must be effortless and must start before the web app exists. **[call]**

**Outcome integrity [call]:** every submission is stored append-only with a row hash; Form
edits and resubmissions are kept as flagged submissions, never overwrites. The scored
outcome for day D is the first valid submission after D's lock and before D+1 06:00 IST;
later ones are stored but excluded from headline scores. Outcomes join the hash chain.

- **Now:** a mobile-friendly Google Form (mood, energy, soreness 1–10, optional note,
  plus up to five optional yes/no **behaviour tags** — alcohol, caffeine after 2pm, late
  meal, high stress, hard training — borrowed from WHOOP's journal idea); an import job
  reads responses directly from the Google Forms API (no Sheet) with their submit timestamp. Tags are inputs
  for the investigator, never forecast targets. **[call]**
- **Later (Phase 7):** a journal form in owner mode replaces it. Both sources are kept
  with provenance; entry latency is recorded (late entries flagged as lower quality).

### 6.6 Agent layer

- **Google ADK 2.12.x**, pinned. Orchestration as an ADK graph `Workflow` with
  deterministic steps and LLM steps; delegation modes set explicitly (fixes today's bug
  where `sub_agents` default to `chat` and the orchestrator can't synthesise). **[call]**
- **Two topologies behind one config switch:** a **single agent** with all tools, and
  the **orchestrator + data scientist / domain expert / coach** variant. Both are
  evaluated identically; whichever wins on evals is the default. **[call]**
- **Models:** Gemini 3.5 Flash-Lite everywhere by default (cost); Gemini 3.8 Flash only
  where an eval shows Flash-Lite falls short; Gemini Embedding 2 for retrieval; all IDs in
  config. **[call]**
- **Code execution:** a sandboxed Python/pandas executor (local container in dev; a
  managed sandbox wrapped as a tool when deployed — exact mechanism **[builder]**, given
  open ADK issue #5315).
- **Receipts:** every numeric claim carries a receipt = {code or SQL, input data
  snapshot hash, output value, timestamp, executor}. Receipts are stored and can be
  re-run from the UI to reproduce the value.
- **Tools:** read-only only. `run_sql` hardened with three layers: SQLite authorizer
  (allowlisted statements/functions), progress-handler timeout, and statement parsing;
  the current keyword blocklist (which wrongly blocks `replace()`) is removed.
- **Untrusted text** (journal notes, device/source names) is wrapped and labelled as
  data before it reaches any model.
- **Human approval** (`require_confirmation`) on any action that changes state, e.g.
  saving a memory.
- **Memory:** typed facts and episodes in SQLite with validity windows behind ADK's
  memory interface; vector retrieval over episodes (journal + anomaly notes);
  user-visible and editable in owner mode. Vertex Memory Bank is an optional backend,
  not a dependency. **[call]**
- **Literature RAG (later phase):** Europe PMC abstracts for the domain expert, hybrid
  retrieval, citations verified against the source; unverifiable claims dropped.
- **Context:** the agent reads computed summaries ("sensor captions"), not raw rows.

### 6.6a Investigator loop (the agentic core)

- **When:** after each nightly scoring run.
- **What:** for the day's largest misses (by RPS, across forecasters), an investigator
  agent plans an inquiry, runs code over the substrate and journal (including behaviour
  tags and the wrapped note text), and writes one or more **hypotheses** — each with its
  receipts, the evidence n, and a status (`open`, `supported`, `refuted`).
- **Memory:** hypotheses are stored as typed memory with validity windows; owner can view
  and delete them. They are summaries, not raw data.
- **Use:** forecaster 7 reads the current hypotheses (and only those) before betting.
  Hypotheses are re-tested as new days arrive; refuted ones stop being shown to it.
- **Measured:** 6 vs 7 on the scoreboard answers "does self-reflection help?"; the
  investigator's hypotheses are also audited (fraction later supported vs refuted).
- **Experiment designer (later, human-approved):** for a well-supported hypothesis the
  agent may propose a small randomized self-experiment; it runs only on owner approval
  (`require_confirmation`) and is tracked in the ledger.
- **Guardrails:** wellness language only; hypotheses are labelled associations; the
  investigator cannot see unmatured forecasts or future journal entries (no leakage).
- **Cost:** Flash-Lite, at most a few misses per night — cents per month.

### 6.7 Evaluation

Built on ADK eval run through pytest, plus a small stats module. **[call]**

| Suite | Size (target) | Cadence |
|---|---|---|
| Core behaviour (grounding, gap admission, receipts present, routing) | ~40 | 10-case subset per PR; full weekly / on demand |
| Numeric ablation: no tools / tools / tools+code / single agent / multi-agent | ~60 | on demand (milestones) |
| Medical boundary (diagnosis, dosing, emergencies, over-claiming) | ~30 | every PR |
| Security: poisoned data, SQL bypass, DoS | ~40 | SQL per PR (no LLM); injection weekly |
| Multi-turn simulated users | 10 scenarios × 2 personas | on demand |

Cadence is set by the budget **[call]**: CI evals run on synthetic fixtures with a
free-tier key; real-data runs are rare, owner-triggered, and costed before running.

- Numeric answers are graded against fixture-computed truth; open-ended answers by
  **binary checklist rubrics**.
- **LLM judge:** one binary judge per failure mode, validated on ~40 owner-labelled
  examples; report TPR/TNR and corrected pass rates.
- **Statistics:** k/n with Wilson 95% intervals; paired McNemar between configurations;
  README states that this size detects tens-of-points gaps, not 2–3 points.
- **Fixtures:** deterministic fixture databases (synthetic) for CI; the owner's real
  data is never required by CI.
- **Real-data ablation:** the PHIA-style ablation and single- vs multi-agent comparison
  also run on the real database in an **owner-only local runner** with truth computed from
  the real data; only aggregates leave the machine. **[call]**
- **PR gate:** must-pass cases + regression check vs `main`; fail on any
  `NOT_EVALUATED` result.
- Cost per full run and per-turn latency/tokens are recorded and published.

### 6.8 Observability

- OpenTelemetry GenAI spans (agent, model, tool) → Phoenix locally, Cloud Trace when
  deployed. Message content capture **off** in deployed spans (no health data in traces).
- Token, cost and latency per turn aggregated for the README scorecard.
- At least one published trace-based failure retro.

### 6.9 Security and privacy

- Threat model in the README framed by the "lethal trifecta" (private data, untrusted
  content, egress) showing where each leg is cut.
- Model Armor on model inputs/outputs in deployment (free tier); per-agent tool allowlists.
- **No public deployment** **[owner]**. The owner service runs behind Cloud Run IAP
  (owner identity only). A `DATA_MODE` setting (real / synthetic) enforces which substrate
  a process may open; the synthetic mode powers fixtures, the video and screenshots. A
  public synthetic variant is defined in Terraform but deployed only briefly, if at all,
  to learn the pattern, then destroyed. **[call]**
- Secrets (OAuth client, refresh token) in Secret Manager; nothing secret in the repo.
- **Synthetic twin:** generated from the real data with simple seasonal/AR/copula
  models (no SDV — source-available licence), published with a fidelity report
  (marginals, autocorrelation, cross-correlations) and a privacy check (no real day
  reproducible). The twin models wearables **and** journal fields, so the video can show a
  **simulated ledger** on synthetic journals, clearly labelled. Real results appear publicly
  only as aggregates: skill scores with n and reliability plots; never raw series, raw
  value distributions or day-level values. **[call]**

### 6.10 Protocols

- **MCP server** (spec 2026-07-28, `mcp` SDK 2.x): read-only tools + resources over the
  substrate; stdio and Streamable HTTP; follows MCP security best practices (no token
  passthrough, scope minimisation). Treated as table stakes, not a differentiator.
- **AG-UI 1.0** between agent API and web UI.
- ~~A2A 1.0 + LangGraph client~~ — cut by the owner (2026-10-20) to keep scope solo-sized.

### 6.11 Web experience

Next.js 16 + AG-UI (`ag-ui-adk`) with CopilotKit or assistant-ui (**[builder]** picks
after a spike). Runs locally by default; deployable as the IAP owner service. Views (trimmed by the owner, 2026-10-20): the **forecast ledger** (scoreboard, calibration, real n) and **receipts** (ask a question, open the code behind each number). Chat streams tool calls into these views. Mode banner always shows "synthetic demo" vs "owner".
Visual design follows a deliberate direction, not a template **[builder]**.

### 6.12 GCP deployment

- **Always on (free tier):** Cloud Run **jobs** for sync, quality, forecast-lock, score,
  digest; orchestrated by **Workflows**, triggered by **Cloud Scheduler**; Secret Manager;
  GCS; BigQuery within the free tier.
- **Deploy to learn, scale to zero:** Cloud Run **services** `api`, `web`, `mcp` as the IAP
  owner variant with `min-instances=0` (no idle cost). **[call]**
- SQLite lives in a private GCS bucket and is copied to local disk for each job/run;
  writes upload a new object version. Never written through a FUSE mount. **[call]**
- **BigQuery** mirror of daily tables (for `AI.FORECAST` and a read-only ADK BigQuery
  toolset).
- Artifact Registry (with a cleanup policy to stay under the free storage tier), Cloud Run
  spend cap, budget alerts, Gemini key quotas, audit logs.
- **Terraform** for all infra (generated via `agents-cli` where it fits, then owned);
  **GitHub Actions** with Workload Identity Federation (no service-account keys).
- Region: a free-tier US region (e.g. `us-central1`) so GCS and Cloud Run free tiers apply. **[call]**

### 6.13 Repository and tooling

- A **new repository under `kb2326`** with fresh history (private until the launch
  review, then public **[call]**); the first commit
  imports the parts of this repo that carry over (client allowlist, auth, loops, tests),
  then they are refactored in place. **[call]** Name: see §10.
- **uv workspace** monorepo, pnpm for the web app:
  `apps/{api,web,jobs,mcp}`, `packages/{health_core,health_data,health_agents,health_eval,health_synth}`. Exact package split **[builder]**.
- Python 3.13, ruff, pyright as the CI type gate (ty non-blocking), pydantic v2 +
  pydantic-settings, Typer CLIs, structlog, pre-commit, Docker.
- Commits authored as "Karthick Balaje Gopalakrishnan Elango" with the owner's personal
  email (karthickbalaje01@gmail.com) **[owner]**; `gh` is switched to `kb2326` (done).
- **Never committed:** `data/`, `config/` secrets, tokens, real-data-derived research
  facts. The research notes contain personal facts (history start, wear counts) and must
  be scrubbed or kept out of the public repo.

### 6.14 Publishing

**Channels [owner]:** GitHub README, a **LinkedIn post**, a **Medium article**, and a
**motion video made with Claude** ("Claude motion"; exact tool confirmed when Phase 8
starts **[builder]**).

README as a product spec: pitch, embedded video, architecture (Mermaid), eval scorecard
with baselines/intervals/cost/latency, forecast-ledger results with real n, threat model,
the seven methodological cautions (07), MCP config, ADRs, a "what it costs to run" table,
disclaimers. The Medium article tells the keeping-score story; the LinkedIn post links
both. Static scorecards may be served free via GitHub Pages.

---

## 7. Phases

The data clock runs first; evidence before polish. **[call]**

| # | Phase | Delivers | Exit check |
|---|---|---|---|
| 0 | Research & ground truth | Research 01–08, live API verification, OAuth repaired, data audit, project doc | ✅ done 2026-10-20 |
| 1 | Foundation | New `kb2326` repo; uv monorepo; ADK 2.12 pinned with delegation fixed; OAuth client in the personal project, published In Production + extra scopes; reconcile-based sync; full backfill; VACUUM; journal Google Form + import; **thin GCP slice** in `artful-timing-506108-n8` (budget alerts, Secret Manager token, GCS-backed db, Cloud Scheduler → `sync` Cloud Run job) so daily jobs never depend on the laptop | Owner journals from a phone; the cloud sync runs daily; a fresh clone runs tests green |
| 2 | Honest stats + ledger | Wear rules; robust baselines; corrected associations; open readiness score; forecasters 1–6 locking daily (incl. BigQuery mirror + TimesFM, Gemini); event-triggered lock; blinding; WORM bucket + public hash chain; scoring + calibration | Ledger has locked, hash-chained forecasts every day; scoring runs on matured days |
| 3 | Agent core | Graph workflow; both topologies; code executor + receipts; hardened `run_sql`; untrusted-text wrapping; memory; **investigator loop + forecaster 7** | Every numeric answer in a smoke set has a re-runnable receipt |
| 4 | Evals & observability | Suites in §6.7; judge calibration; red-team; CI gate; OTel tracing; scorecard generator | A deliberately regressed prompt fails the PR gate |
| 5 | Protocols | MCP server | Claude Desktop calls a tool via copy-paste config |
| 6 | GCP | Full Terraform; all jobs on Workflows + Scheduler; IAP owner services (scale to zero); synthetic twin + fidelity report; WIF CD; destroy/redeploy drill; cost report | Owner mode works behind IAP; jobs succeed nightly; a month's bill is under $5 |
| 7 | Web experience | Next.js 16 + AG-UI views in §6.11; owner journal replaces the Form | The owner can ask a question and open its receipt; synthetic mode is video-ready |
| 8 | Publish | README-as-spec, ADRs, Claude motion video, Medium article, LinkedIn post; repo made public after a privacy review; fresh-clone test | Clone-and-follow passes on a clean machine; all three channels live |

Literature RAG (§6.6) slots into Phase 3 or after Phase 7, depending on time **[builder]**.
Phases 2 and 3 may run in parallel after Phase 1.

---

## 8. Deliberately skipped

LangGraph rewrite · LoRA/fine-tuning · GKE · Temporal · Composer · VPC-SC · AP2 ·
A2UI · dbt/Dagster/Great Expectations · ChromaDB · SDV · Material for MkDocs ·
multi-cloud (the README maps GCP services to AWS equivalents instead). Reasons in
research note 00 §2 and the project doc's Stack tab.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Too few journal days → empty ledger | Journal Form in Phase 1; show real n; the scoreboard grows over time |
| Forecasters don't beat persistence | Publish it — an honest, expected result (BALMS) |
| Multi-agent loses to single agent | Publish it; default to the winner |
| Real-data leak | Synthetic-only public service; separate SAs; content off in traces; scrub notes |
| Medical-claim scrutiny | Wellness wording; boundary eval suite; disclaimers; AI disclosure |
| Cost runaway | Spend cap, rate limits, Flash-Lite defaults, budget alerts |
| API/model churn | Pinned versions; model IDs in config; price changes tracked |
| Scope creep | Optional items marked; evidence phases first |

## 10. Open questions for the owner

Resolved 2026-10-20 **[owner]**: GCP project `artful-timing-506108-n8`; budget under
$5/month; no paid public deployment; publish via LinkedIn, Medium and a Claude motion
video; commits with the personal email.

Settled as **[call]** (owner may override): publishing line = skill scores, n and
reliability plots only; blinding on; no fixed date — optional items (literature RAG,
multi-turn simulations) are cut first if time runs short.

Nothing still open.
1. ~~Project and repo name~~ — resolved: **Calibrated Health Agent**, `kb2326/calibrated-health-agent` **[owner]**. "Keeps score" stays as the tagline.

## 11. Left to the builder

Exact wear thresholds; statistical model family for forecaster 4; sandbox mechanism;
package split; UI component library (after a spike) and visual design; GCP region;
the exact extra data types; whether literature RAG lands in Phase 3 or later; eval
case wording within the suite targets.

## 12. Independent review resolutions (2026-10-20)

An independent go/no-go review (verdict: **go with changes**) was folded in:

| Finding | Resolution | Where |
|---|---|---|
| Main DB could outgrow an in-memory Cloud Run disk | Daily-only SQLite, 50 MB cap test, reconcile used for parity/wear only, 2 GiB job | §6.1, Phase 1 plan Tasks 4, 9 |
| Outcomes could change after reveal | Append-only `journal_submissions`, outcome window, outcomes hashed | §6.4, §6.5, plan Tasks 3, 6 |
| Hash log not public while repo is private | Separate public `kb2326/cha-ledger-log`; pre-registration as first entry; date + hash only | §6.4 |
| Weak statistical power | One pre-registered primary endpoint; bootstrap/DM intervals; coarse calibration; climatology prior; TimesFM mapping or backtest-only; pinned Gemini forecaster | §6.4 |
| Silent job failures | Log-based alert + email channel in Terraform | plan Task 9 |
| Local/cloud DB drift | GCS source of truth; `db pull`; stale-local guard | §6.1, plan Task 7 |
| Sheets and Terraform details | UNFORMATTED/SERIAL values, positional columns, ADC scopes; budget quota project; Scheduler `oauth_token`; local image build, jobs-only image, no Cloud Build | plan Tasks 6, 8, 9 |
| `task` mode unavailable inside graph workflows | Phase 1 uses `single_turn`; final modes decided with the Phase 3 workflow | plan Task 11 |
| Impact arrives too late | **Public scoreboard on GitHub Pages from Phase 2** (aggregates + "days locked"), fed by the public log | Phase 2 |
| No way to verify claims without a live URL | One-command synthetic demo (`docker compose up`) | Phase 6/7 |
| Engineering too large for one person | **Owner decision 2026-10-20:** cut A2A + LangGraph client; Phase 7 shrinks to the ledger and receipt views; Workflows and Model Armor kept as small learning items in Phase 6 | §6.10, §6.11, §7 |
