# Calibrated Health Agent — Architecture

**Status:** Approved by owner 2026-10-20 · **Date:** 2026-10-20
**Companion to:** `docs/superpowers/specs/2026-10-20-calibrated-health-agent-design.md` (the *what* and
*why*). This document is the *how*, end to end, from vision down to deployment.
Diagrams are Mermaid and render on GitHub.

---

## 1. From vision to architecture

> A personal health agent that **keeps score**: it forecasts how you'll feel tomorrow,
> grades itself against simple baselines on your real data, shows a code receipt for
> every number, and publishes its evals — including where it loses.

Each pillar of the vision becomes one architectural commitment:

| Vision pillar | Architectural commitment | Where |
|---|---|---|
| Real data | Read-only ingestion from the Google Health API into a single system of record; nothing invented, every value traceable to an API data point | §4, §5 |
| Forecasts how you'll feel | A scheduled forecast-lock job writes probabilistic forecasts to an append-only, tamper-evident ledger before the outcome exists | §6 |
| Grades itself against baselines | Several forecasters (baselines, statistical, TimesFM, Gemini) compete on one scoreboard with proper scoring rules | §6 |
| A receipt for every number | Agent answers come from executed code/SQL; each result is stored as a re-runnable receipt | §7 |
| Publishes its evals | Eval suites gate CI; scorecards are generated artifacts, never hand-written | §9 |
| Including where it loses | Single- vs multi-agent and LLM vs baseline comparisons are first-class outputs | §6, §9 |
| Your data, safely | Real data only in owner-only surfaces (IAP or local); public material is synthetic or aggregate; least privilege; no health data in traces | §10, §11 |

### Design principles

1. **Read-only toward the source, append-only toward evidence.** The API is never written; ledger records are never edited.
2. **Compute, don't narrate.** Numbers come from code; models explain them.
3. **Deterministic skeleton, LLM steps where they earn it.** Pipelines and the forecast lock are plain code; LLMs sit inside bounded steps.
4. **Baselines everywhere.** No metric ships without its naive comparator and n.
5. **Privacy by topology, not by promise.** Real data is physically absent from anything public.
6. **Small and boring infrastructure.** Scale-to-zero managed services, one SQLite file, Terraform.
7. **Near-zero cost by construction.** Free tiers, scale-to-zero, Flash-Lite, hard budget guards (§12a).

---

## 2. System context

```mermaid
flowchart LR
  owner([Owner])
  reviewer([Reviewer])
  mcpc([MCP client<br/>Claude Desktop · Cursor])
  watch[[Fitbit / Pixel Watch]]
  ghapi[(Google Health API v4)]
  form[[Journal form<br/>Google Form, read via the Forms API]]
  gemini[(Gemini models<br/>Gemini Enterprise Agent Platform)]
  ks{{Calibrated Health Agent}}
  gh[(GitHub kb2326<br/>code · CI · public hash log)]

  watch --> ghapi
  ghapi -- read-only OAuth --> ks
  owner -- daily journal --> form --> ks
  owner -- IAP sign-in --> ks
  reviewer -- README · Medium · LinkedIn · video --> gh
  mcpc -- MCP --> ks
  ks -- prompts / tool results --> gemini
  ks -- daily ledger hash --> gh
```

External dependencies: the Google Health API (data), Gemini (reasoning), Google Forms API
(journal until the owner UI exists), GitHub (code, CI, public hash log).

The Phase 1 cloud slice is described in detail in [cloud-design.md](cloud-design.md).

---

## 3. Containers (deployed shape)

```mermaid
flowchart TB
  subgraph EXT["External"]
    direction LR
    ghapi[("Google Health API<br/>read-only")]
    form[("Journal Form<br/>Forms API")]
    gemini[("Gemini<br/>paid key · quota-capped")]
  end

  subgraph GCP["GCP project artful-timing-506108-n8 · us-central1 · Terraform · budget $5"]
    direction TB
    subgraph ORCH["Orchestration"]
      direction LR
      sched["Cloud Scheduler"] --> wf["Workflows"]
    end
    subgraph JOBS["Cloud Run jobs · free tier"]
      direction LR
      sync["sync"] --> quality["quality + wear"] --> lock["forecast-lock"]
      score["score"] --> digest["digest"]
      mirror["bq-mirror"]
    end
    subgraph OWNER["Owner services · IAP · min-instances 0"]
      direction LR
      web_o["web · Next.js"] --> api_o["api · ADK agent"]
      mcp_o["mcp · read-only"]
    end
    subgraph STORE["Storage"]
      direction LR
      gcsdb[("GCS · health.db<br/>versioned, private")]
      worm[("GCS · ledger<br/>retention-locked")]
      bq[("BigQuery<br/>AI.FORECAST")]
      sm[("Secret Manager")]
    end
    obs["Cloud Trace · Logging"]:::obs
    ORCH --> JOBS
    JOBS --> STORE
    OWNER --> STORE
    JOBS -.-> obs
    OWNER -.-> obs
  end

  ghapi --> sync
  form --> sync
  gemini <--> lock
  gemini <--> api_o
  lock -- "daily hash" --> ghrepo[("GitHub · public hash log")]
  ghact["GitHub Actions · WIF"] -- deploy --> GCP
  laptop["Owner laptop · local dev<br/>synthetic mode for the video"] -.-> gemini
  classDef obs stroke-dasharray: 4 3
```

| Container | Runtime | Purpose | Data it may touch |
|---|---|---|---|
| `sync` job | Cloud Run job | Pull API deltas + journal entries; write raw points | real db (rw) |
| `quality` job | Cloud Run job | Wear detection, daily aggregation, pandera checks | real db (rw) |
| `forecast-lock` job | Cloud Run job | Run all forecasters, lock forecasts, write hash | real db (rw), ledger bucket (append), BigQuery (read) |
| `score` job | Cloud Run job | Score matured forecasts against journal | real db (rw) |
| `bq-mirror` job | Cloud Run job | Copy daily tables to BigQuery | real db (r), BigQuery (rw) |
| `digest` job | Cloud Run job | Weekly digest + aggregate scorecard | real db (r) |
| `api` (owner) | Cloud Run service, IAP | ADK agent over real data | real db (r), BigQuery (r) |
| `web` (owner) | Cloud Run service, IAP | UI incl. journal and memory | via api only |
| `mcp` (owner) | Cloud Run service, IAP | Read-only MCP tools | real db (r) |
There is **no public deployment** (owner decision: not worth paying for). Owner services
run with `min-instances=0`, so they cost nothing while idle; jobs stay inside free tiers.
Each service and job runs as its **own service account**. A public synthetic variant is
defined in Terraform as a learning exercise (no IAM path to real data, `DATA_MODE=synthetic`)
and is deployed briefly, if at all, then destroyed.

---

## 4. Google Health API usage — making the most of it, purely

### 4.1 Data purity

- **Raw first.** Every API data point is stored as returned (`raw_json`), with its data
  source (device/platform), before any transformation. Daily values are *derived* and
  always re-computable from raw.
- **Reconciled streams for totals.** Summed types (steps, distance, calories, active
  minutes) are taken from `dataPoints.reconcile` (merges multiple sources into one
  stream) or `dailyRollUp`, so phone + watch never double-count. Today's sync lists raw
  points per source without reconciling — fixed in Phase 1.
- **No measurement mixing.** HRV from different statistics (e.g. RMSSD vs SDNN) or
  devices is never averaged together; source is a column, not a footnote.
- **What the API already processed** (e.g. device-computed HRV, sleep stages, resting HR)
  is labelled as device-derived in receipts.
- **The journal is the only non-API data**, and is labelled as self-report with entry time.

### 4.2 Endpoint map

| Method | Use in this system | Status today |
|---|---|---|
| `dataPoints.list` | Raw samples for point types (HRV, SpO2, sleep sessions, exercise) | used |
| `dataPoints.reconcile` | De-duplicated multi-source stream for summed types | **add** |
| `dataPoints.dailyRollUp` | Civil-day aggregates (≤90 days/call; 14 for HR, calories, active minutes) | used |
| `dataPoints.rollUp` | Physical-interval aggregates (heart rate windows) | used |
| `dataPoints.get` | Receipt drill-down to a single source point | **add** |
| `dataPoints.exportExerciseTcx` | Workout detail (route-free summary only; location not requested) | later, optional |
| `users.getProfile` / `getSettings` | Units, time zone, age/sex for context (needs `profile.readonly`, `settings.readonly`) | **add scopes** |
| `users.pairedDevices.list/get` | Device inventory → wear detection and source labels | **add** |
| `users.getIdentity` | Stable user id for the subscription | add with webhooks |
| `projects.subscribers` + `subscriptions` | Push notifications when new data lands (replaces hourly polling) | Phase 6+ |
| `getIrnProfile`, ECG | Cardiac notifications/ECG — **excluded**: closest to clinical territory | deliberately unused |
| any create/patch/delete/update | — | **unreachable** (client allowlist + read-only scopes) |

### 4.3 Data types

- **Synced today (11):** steps, active-minutes, distance, total-calories, exercise, sleep,
  heart-rate, daily-resting-heart-rate, heart-rate-variability, oxygen-saturation, weight.
- **Add (readable, useful for forecasting):** daily-heart-rate-variability,
  daily-oxygen-saturation, daily-respiratory-rate, respiratory-rate-sleep-summary,
  daily-sleep-temperature-derivations, active-zone-minutes, time-in-heart-rate-zone,
  daily-vo2-max, sedentary-period, floors. Final list after checking what the device emits.
- **Not readable by design of the API:** `moods`, `symptoms` (write-only scopes) — which
  is why the journal is this project's own.
- **Not requested:** location, nutrition (unless the owner logs food), reproductive health.

### 4.4 Limits handled

300 requests/min/user (backoff on 429/504) · 10,000 items/page (25 for sleep and exercise)
· rollup windows split per type · bounded pagination (three exit conditions, one of which
trusts the server) · token refresh with the consent screen **In Production**.

---

## 5. Data model and daily data flow

### 5.1 Storage layers

Phase 2 status: `forecasts`, `snapshots` (the feature snapshot per lock), `ledger` (the hash
chain) and `scores` are live (schema v3, append-only by trigger). Wear is computed on demand
by `health_ledger.wear` rather than stored. `daily_metrics` carries the `source` its value
came from: types listed with `sources` in `config/health.yaml` take one preferred source per
day (HRV: Fitbit RMSSD only; resting HR: Fitbit, else Apple), never a mean across sources.

```
raw_points        API data as returned + source + fetched_at        (append; idempotent upsert)
sync_state        cursor per data type                               (committed with rows)
daily_metrics     derived per day per metric + worn flag + n          (recomputable)
wear_days         per day per metric family: worn / not worn + rule  (recomputable)
journal_submissions  append-only: values · note · submitted_at · source · row_hash · status (ok/late/edited/invalid)
journal_outcome      view: first ok submission per day inside its window
forecasts         forecaster · target · day · distribution · inputs_hash · locked_at (append-only)
scores            forecast_id · RPS · log score · matured_at
receipts          code/SQL · data snapshot hash · output · executor · created_at
memory_facts      typed fact · valid_from · valid_to · approved_at
memory_episodes   text · embedding · day · source
```

SQLite is the system of record, held in GCS as the single source of truth (local writes
pull first). It holds daily values and point/session raw data only, capped at 50 MB;
minute-level reconciled streams are used for parity and wear checks, never stored in it.
DuckDB attaches it for analytics; Parquet exports feed BigQuery and the synthetic-twin builder.

### 5.1a Which day a value belongs to (the civil-day rule)

Every daily value belongs to one **civil day in the owner's time zone** (`Settings.timezone`,
Asia/Kolkata), never to a UTC date. The rule is defined once, in
`packages/health_data/src/health_data/civil.py`; `raw_points.civil_date` stores the result.

| Data | Belongs to |
|---|---|
| dailyRollUp totals (steps, distance, calories, active minutes, floors, zone minutes, sedentary time) | the bucket's civil day; requested as owner-zone dates |
| heart-rate (24 h `rollUp` buckets) | the owner-zone day of the bucket start; windows start at owner-zone midnight |
| daily summaries (`*.date`: resting HR, daily HRV, SpO2, respiratory rate, skin temperature, VO2 max) | the API's `date` |
| sleep | the owner-zone day the session **ends** (last night's sleep is the morning of D) |
| other intervals (exercise) | the owner-zone day the interval starts |
| samples (HRV, SpO2, weight, nightly respiratory summary) | the owner-zone day of the sample time |
| journal | the date the owner enters (the evening of D) |

Request windows are computed in the owner zone and converted per filter: physical-time
filters get the UTC instant of owner-zone midnight, civil-time filters the owner-zone wall
clock, date filters the owner-zone date. Every sync covers **today** plus a trailing
**3-day lookback** (`civil.LOOKBACK_DAYS`), or further back to the last successful sync after
missed runs, so late uploads land and the 12:00 lock sees last night's sleep, HRV and resting
HR. Storage is idempotent: server buckets are upserted (a day still in progress is replaced by
its later value), points are upserted on their unique key, and `inserted` counts only
new-or-changed rows. `cha-data db repair` re-fetches history and recomputes daily values
under this rule.

### 5.2 A day in the life (owner time zone)

```mermaid
sequenceDiagram
  autonumber
  participant W as Watch → Health API
  participant S as sync + quality (hourly 05:00–12:00)
  participant L as forecast-lock
  participant O as Owner
  participant J as Journal (Form/UI)
  participant C as score (21:00–02:00)
  W->>S: overnight sleep, HRV, RHR sync to cloud
  S->>S: ingest, reconcile, wear check, aggregate
  S->>L: trigger when last night's sleep is present
  Note over L: or at 12:00 deadline with "no-sleep-data" inputs
  L->>L: all forecasters → distributions for today
  L->>L: write to ledger + WORM object + hash → GitHub
  Note over O: today's forecasts hidden from owner (blinding)
  O->>J: evening entry: mood, energy, soreness
  J->>C: next import picks it up
  C->>C: score today's locked forecasts, update scoreboard
  Note over C: forecasts reveal after scoring
```

Rules:
- A forecast for day D may use all data **through the end of the sleep that ended on the
  morning of D**. Lock is **event-triggered** (sleep record present) with a **12:00 local
  deadline**; deadline locks record which inputs were missing.
- A journal entry submitted **before** that day's lock invalidates the day for scoring.
- **Blinding (default):** unmatured forecasts are hidden from every owner-facing surface
  — UI, chat, digest, MCP, memory — until the day is scored. (Owner can opt out; opting out
  is logged and those days are flagged.)

---

## 6. Forecast ledger

```mermaid
flowchart LR
  feat[Feature snapshot<br/>sensor captions + hash] --> f1[Climatology]
  feat --> f2[Persistence]
  feat --> f3[Seasonal-naive]
  feat --> f4[Statistical model]
  feat --> f5[TimesFM · BigQuery AI.FORECAST]
  feat --> f6[Gemini forecaster]
  feat --> f7[Gemini + own notes]
  notes[(Investigator hypotheses)] --> f7
  f1 & f2 & f3 & f4 & f5 & f6 & f7 --> lockrec[Locked record<br/>distribution over 1–10]
  lockrec --> worm[(Retention-locked GCS object)]
  lockrec --> hash[Daily hash chain → public GitHub log]
  journal[Journal outcome] --> scoring[RPS · log score · skill vs climatology & persistence]
  lockrec --> scoring --> board[Scoreboard · reliability plots · real n]
  scoring --> inv[Investigator agent<br/>code + receipts on biggest misses]
  inv --> notes
```

- **Targets:** mood, energy, soreness (1–10), each a full probability distribution.
- **Forecasters 1–6 all lock from Phase 2** (TimesFM via BigQuery and Gemini included), so
  no forecaster loses live days.
- **Scoring:** ranked probability score (ordinal), log score, skill scores vs climatology and
  persistence, reliability diagrams, rolling-origin windows.
- **Evidence integrity:** each day's forecasts **and imported outcome** are hashed and
  chained (hash includes the previous day's hash); records go to a **retention-locked**
  bucket and the chain hash (date + hash only) is pushed to the public repo
  `kb2326/cha-ledger-log`, whose first entry is the hash of the pre-registered analysis plan.
  A **GitHub Pages scoreboard** (aggregates and "days locked") is published from it.
- **Primary endpoint:** energy, RPS skill vs persistence, with paired block-bootstrap
  intervals; calibration via PIT or coarse bins.
- **Live vs backtest:** the scoreboard counts **live locked** forecasts only. Rolling-origin
  backtests (useful for forecasters added later) appear in a separate, clearly labelled panel.
- The Gemini forecaster receives exactly the same feature snapshot as the statistical
  models — no extra context — so the comparison is fair.

---

## 7. Agent layer

### 7.1 Request flow (owner asks a question)

```mermaid
sequenceDiagram
  autonumber
  participant U as Web UI (AG-UI)
  participant A as ADK Workflow
  participant G as Guardrails (Model Armor, wrappers)
  participant T as Tools (read-only)
  participant X as Code sandbox
  participant R as Receipts
  U->>A: question (streamed session)
  A->>G: screen input
  A->>A: plan (built-in thinking)
  A->>T: data_catalog / query_metric (look before asking)
  A->>X: pandas / SQL computation
  X->>R: store {code, snapshot hash, output}
  R-->>A: value + receipt id
  A->>G: screen output (no diagnosis, wellness wording)
  A-->>U: streamed answer + tool cards + receipt links + n
```

### 7.2 Components (built in Phase 3)

Phase 3 design: `docs/superpowers/specs/2026-10-23-phase-3-agent-core-design.md`; workflow
shape proven in ADR `docs/adr/0001-phase3-workflow.md`.

| Component | Design |
|---|---|
| Framework | Google ADK 2.12.0 pinned; graph `Workflow`: `screen` (deterministic) → answer (LLM) → `verify_receipts` (deterministic, one retry) |
| Topologies | Phase 4.5 (ADR 0007): `single` (one tool-loop agent with thinking, 14 tools; default) and `team` (alias `multi`: the same agent plus a coach and a domain expert as `AgentTool`s it may consult). The Phase 3 router → specialists → synthesizer pipeline was retired after evaluation. `CHA_TOPOLOGY` |
| Models | Gemini 3.5 Flash-Lite everywhere (Vertex AI, global endpoint); `gemini-embedding-2` for memory; IDs and prices in `Settings` |
| Code execution | `run_python`: a fresh subprocess per call (`-s -P`, scrubbed environment, empty temp dir), AST allowlist, an audit hook that blocks sockets, processes, ctypes and file writes, Linux rlimits (CPU 10 s, 1.5 GiB, no files, no forks), 15 s timeout. Data arrives as JSON (a leakage-safe bundle cut at an as-of day), never the database. Defense in depth, not a VM boundary; gVisor underneath on Cloud Run |
| Receipts | Content-addressed `{code, data hash, as-of, output, executor}`; chat receipts in the laptop's `agent.db`, investigator receipts in `health.db`. `cha receipt <id> --rerun` reproduces the value or says the data changed |
| `run_sql` | SQLite `mode=ro` + authorizer (SELECT, allowlisted tables and functions; ledger and agent tables blinded) + 2 s progress-handler limit + single statement; row cap 500; every call leaves a receipt |
| Verification | Every number in an answer must equal (at its precision) a value in this turn's tool outputs; dates, window lengths and the question's own numbers exempt; otherwise one retry (an empty draft is retried, and the last real draft is used if needed), then a quiet note naming the figures not computed by a tool (Phase 4.5; previously an `unverified:` footer) |
| Untrusted text | Journal notes, device/source names, sandbox output and hypothesis statements wrapped in `<untrusted>` before any prompt; every instruction says what that means |
| Memory | `HealthMemoryService(BaseMemoryService)` over `agent.db`: facts saved only via `save_fact` (`require_confirmation`, a y/n in the terminal) with validity windows; journal notes and hypotheses embedded and searched by cosine; ADK `load_memory` tool |
| Ledger access | `get_scoreboard` (settled aggregates) only; unsettled forecasts invisible under blinding |
| Investigator | In the nightly job after settle and re-test: one Flash-Lite agent studies the night's biggest forecaster-6 miss with `run_python`/`run_sql`, capped at 6 calls, 15k input / 2k output tokens and 180 s; proposals become hypotheses only after `validate` (sandboxed condition over lock-time columns, 3+ matching days, not a duplicate, no disease words). `retest` judges each on days settled after it was written (open → supported/refuted by fixed rules) |
| Forecaster 7 | Forecaster 6's prompt plus up to five live hypotheses (always-present notes section); notes stored in `lock_notes` and hashed into the lock's chain entry |
| Budget | `agent_runs` records tokens and dollars; $0.30/month cloud cap (investigator + forecaster 7) and $0.30/month laptop chat cap, enforced in code |
| Interfaces | `cha` terminal (`ask`, `chat`, `notes`, `receipt`, `memory`, `smoke`); AG-UI (web, Phase 7) and MCP (Phase 5) wrap the same runner |

---

## 8. Interfaces

| Interface | Protocol | Exposes |
|---|---|---|
| Web ↔ agent | AG-UI 1.0 over SSE (`ag-ui-adk`) | streamed text, tool calls, step timeline, confirmations |
| MCP server | MCP spec 2026-07-28, stdio + Streamable HTTP | read-only tools (metrics, series, scoreboard, receipts) + resources per data type |
| Jobs | Workflows → Cloud Run jobs | sync, quality, lock, score, mirror, digest |
| Journal | Google Form, read directly via the Forms API (now), owner web form (later) | daily entries with timestamps |

---

## 9. Evaluation and observability

```mermaid
flowchart LR
  fx[(Synthetic fixture DBs)] --> ci[GitHub Actions<br/>unit · lint · types · eval subset · SQL red-team]
  ci --> gate{PR gate<br/>must-pass + McNemar vs main}
  fx --> nightly[Nightly: full suites · ablation · injection]
  real[(Real db, owner machine)] --> local[Owner-only eval runner<br/>real-data ablation]
  local --> agg[Aggregates only]
  nightly --> card[Scorecard generator]
  agg --> card --> readme[README scorecard]
  traces[OTel spans] --> phoenix[Phoenix local] & ctrace[Cloud Trace]
  traces --> cases[Failure cases → new eval cases]
```

- **CI uses synthetic fixtures only**; the **real-data ablation** (no tools / tools / code /
  single vs multi) runs in an owner-only local runner and publishes aggregates only.
- Judge: one binary judge per failure mode, calibrated on owner labels (TPR/TNR reported).
- Stats: Wilson 95% intervals; paired McNemar; cost and latency per run.
- Tracing: OTel GenAI spans (agent, model, tool); deployed spans carry **no message
  content**; token/cost/latency aggregated per turn.

---

## 10. Security architecture

| Threat (lethal-trifecta leg) | Control |
|---|---|
| Private data exposure | Real data only in owner services behind IAP (owner identity only) or on the owner's machine; nothing public has an IAM path to it |
| Untrusted content steering the agent | Stored text wrapped as data; Model Armor; per-agent tool allowlists; red-team suite with poisoned DBs |
| Exfiltration / egress | Tools are read-only; sandbox has no network; MCP server read-only, no token passthrough |
| SQL abuse / DoS | Authorizer allowlist, timeouts, row caps, single statement |
| Secret leakage | Secret Manager; WIF for CI (no keys); secrets never in repo or images |
| Ledger tampering | Append-only forecasts and journal submissions, retention-locked bucket, public hash chain in `kb2326/cha-ledger-log` |
| Silent failure (the old 2-month gap) | Log-based alert on job failure → email; job exits non-zero on any failed step |
| Medical harm | Wellness-only wording, boundary eval suite, disclaimers, AI disclosure |
| Cost runaway | No public endpoint; min-instances 0; Gemini key quotas; Flash-Lite defaults; Cloud Run spend cap; budget alerts at $2/$4 |

---

## 11. Privacy architecture

| Surface | Real data? | What appears |
|---|---|---|
| Owner web/api/mcp (IAP or local) | yes | everything, to the owner only |
| Video (Claude motion) | **no** | synthetic-mode UI; a **simulated** ledger on synthetic journals, labelled as such |
| README / Medium / LinkedIn | aggregates only | skill scores with n and reliability plots; never raw series, raw distributions or day-level values |
| Traces / logs | no content | spans without message bodies |
| GitHub | no | code, synthetic data, public hash chain (hashes reveal nothing) |

**Synthetic twin:** built from real data with seasonal/AR/copula models (wearables *and*
journal, so the simulated ledger in the video is meaningful); published with a fidelity report whose
real-side statistics respect the owner's publishing line; privacy check that no real day is
reproduced.

---

## 12. Environments

| Environment | Where | Data | Purpose |
|---|---|---|---|
| Local dev | Owner's Windows machine (+ containers) | real db copy, fixtures | build, owner-only evals |
| CI | GitHub Actions | synthetic fixtures | tests, eval gate |
| Owner prod | GCP `artful-timing-506108-n8`, `us-central1`, IAP | real | daily jobs, private use |
| Synthetic | local (and optionally a short-lived Cloud Run deploy) | synthetic twin | video, screenshots, learning the public pattern |

## 12a. Cost architecture (budget: under $5/month)

| Item | Free tier used | Expected monthly cost |
|---|---|---|
| Cloud Run jobs (6 short daily/hourly jobs) | 180k vCPU-s, 360k GiB-s | $0 |
| Cloud Run services (owner, min-instances 0) | 2M requests | $0 |
| Cloud Scheduler (≤3 jobs) · Workflows (≤5k steps) | yes | $0 |
| Cloud Storage (db versions, ledger bucket) — US region | 5 GB | $0 |
| BigQuery (mirror + `AI.FORECAST`) | 10 GB storage, 1 TB query | ≈ $0 |
| Secret Manager · Artifact Registry (cleanup policy) · Trace · Logging | yes | $0 |
| Model Armor | 2M tokens | $0 |
| Gemini, real data: daily forecaster + owner chat (Flash-Lite) | — | ≈ $0.10–1 |
| Gemini, synthetic-fixture evals / CI | free-tier key (synthetic data only) | $0 |
| Gemini, rare real-data ablation runs (costed before running) | — | ≈ $1–2 per run |
| **Total target** | | **≈ $1–2, hard ceiling $5** |

Guards: budget alerts at $2 and $4; Cloud Run spend cap; per-day quota on the paid Gemini
key; Flash-Lite by default; no always-on instances; Artifact Registry cleanup policy;
message content off in traces (also keeps span volume small).

---

## 13. Repository layout (target)

```
apps/
  api/        ADK agent service (AG-UI endpoint)
  web/        Next.js 16 app
  jobs/       sync · quality · forecast-lock · score · bq-mirror · digest
  mcp/        read-only MCP server
packages/
  health_core/    settings, models, logging, DATA_MODE
  health_data/    API client (allowlist), storage, wear rules, aggregation
  health_ledger/  forecasters, locking, scoring, hash chain
  health_agents/  workflow, topologies, tools, sandbox, receipts, memory
  health_eval/    suites, judge, stats, scorecard
  health_synth/   synthetic twin + fidelity report
infra/        Terraform (project, IAM, Cloud Run, Workflows, Scheduler, buckets, BigQuery, WIF)
evals/        cases and fixtures
docs/         architecture, ADRs, spec, runbooks
```

---

## 14. Phase-to-architecture map

| Phase | Architecture that becomes real |
|---|---|
| 1 Foundation | Repo + layout; API client with reconcile/profile/devices; **thin GCP slice**: personal project, Secret Manager token, GCS db, Scheduler → one `sync` job; journal Form import |
| 2 Ledger | `quality`, `forecast-lock`, `score` jobs; all six forecasters (incl. BigQuery mirror + TimesFM, Gemini); WORM bucket + hash chain; blinding |
| 3 Agent core | **Live 2026-10-24:** workflow, both topologies, sandbox, receipts, guarded tools, memory, investigator in the nightly job, forecaster 7 |
| 4 Evals | Fixtures, suites, judge, CI gate, owner-only runner, tracing |
| 5 Protocols | MCP server |
| 6 Deploy | Full Terraform, IAP owner services (scale to zero), all jobs on Workflows, synthetic twin, WIF CD, destroy/redeploy drill, cost report, webhooks |
| 7 Web | AG-UI app with two views: forecast ledger and receipts |
| 8 Publish | README scorecard, ADRs, video, blog |

---

## 15. Decisions

Owner (2026-10-20): GCP project `artful-timing-506108-n8`; spend under $5/month; no paid
public deployment, but learn deployment through this project; publish via LinkedIn, Medium
and a Claude motion video; commits with the personal email; GitHub `kb2326`.

Calls (owner may override): publishing line = skill scores, n, reliability plots; blinding
on; Flash-Lite by default; region `us-central1`; repo private until launch review.

Name (owner, 2026-10-20): **Calibrated Health Agent**, repo `kb2326/calibrated-health-agent`; "keeps score" remains the tagline.
