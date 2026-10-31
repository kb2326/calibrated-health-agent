# Deep research synthesis — 2026-10-20

Six parallel research streams (files 01–06 in this folder) plus a live audit of
the Google Health API connection and the owner's real data. This note resolves
conflicts between streams and states the recommended direction. Claims carry
the evidence posture of the stream file they come from; verify model names and
prices against primary pages before committing (several were fast-moving).

## 1. Ground truth from the live audit (2026-10-20)

- Google Health API connection **live** after re-auth. Docs confirm: successor to
  the Fitbit Web API (Fitbit shut-off 2026-10-30), ~44 data types, no stated
  history limit, 300 req/min/user, webhook subscriptions exist.
- Real history spans ~7 months; only a recent window had been synced.
- Wear is patchy recently: sparse overnight wear, with gaps in the daily series.
- The journal has just started. A few predictions exist, none scored. Learning loop never closed.
- The local `health.db` holds a few MB of data in a heavily over-allocated file (mostly free pages). Not "big data".
- OAuth app is in **Testing** mode → refresh tokens die after 7 days (root cause of
  the long sync gap). Must publish consent screen "In Production" for any
  scheduled sync. `profile.readonly`/`settings.readonly` scopes not requested.

## 2. What the streams agree on

| Theme | Consensus |
|---|---|
| Framework | **Keep Google ADK, upgrade 2.7.1 → 2.12.x.** No LangGraph rewrite. (02, 06, 01) |
| Real bug | `sub_agents` default to `chat` mode → orchestrator cannot synthesise across specialists as instructed. Fix with `single_turn`/`task` modes or a graph `Workflow`. (02) |
| Multi-agent honesty | "Multi-agent for its own sake" is a 2026 red flag; publish a **single-agent baseline** on the same evals. (01, 02, 05) |
| Novelty | Three-agent PHA topology copies Google; health MCP connectors are commodity. Differentiation = **measured, calibrated, honest statistics on real longitudinal data**. (01, 04) |
| Signature feature | **Calibrated forecast ledger**: daily probabilistic forecasts of journal fields scored (Brier/CRPS) vs. mean and persistence baselines; Gemini coach is one forecaster among several. No product or paper publishes this. (04) |
| Headline evidence | **PHIA ablation on own data** (no tools / tools / code execution / single agent) with Wilson CIs + McNemar. (05, 02, 04) |
| Code execution | Sandboxed pandas executor for the data scientist; every number carries a re-runnable "receipt". (02, 04) |
| Stats rebuild | Current learn/correlate/analyze would not survive expert review: fixed 0.5 base rate, ~230 uncorrected Pearson tests on autocorrelated data, non-robust z, no wear-detection. (04) |
| Evals | ADK eval (13 criteria, rubrics, user simulation) via pytest; binary checklist rubrics; judge calibrated vs. human labels; ~165 cases; PR gate + nightly. (05) |
| Security | 3-layer `run_sql` guard (authorizer + progress-handler timeout + parse), untrusted-text wrapping for journal notes, poisoned-DB red-team mapped to OWASP Agentic IDs, Model Armor. (05) |
| MCP | Publish a read-only MCP server on spec 2026-07-28 / SDK `mcp` 2.x. Top job keyword (721 postings). (01, 02) |
| Privacy | Never publish raw series (86–100% re-identification). Public demo on a **synthetic twin** with fidelity report; owner mode behind **Cloud Run direct IAP**. (06, 03) |
| Hosting | **Cloud Run** (scale-to-zero, IAP GA, spend caps GA 2026-10-12). Cloud Scheduler → Workflows → Cloud Run jobs for loops. ~$1–15/mo, mostly tokens. (03) |
| Naming | Vertex AI → "Gemini Enterprise Agent Platform"; Agent Engine → "Agent Runtime". Use new names. (01, 02, 03) |
| Tooling | uv workspace, ruff, pyright gate (ty non-blocking), pydantic v2, Typer, structlog; GitHub Actions + Workload Identity Federation; Terraform via `agents-cli`. (03, 06) |
| Skip | AP2, A2UI, Temporal, GKE, VPC-SC, Composer, dbt/Dagster, LoRA, ChromaDB, SDV (BSL licence), Material for MkDocs (maintenance). |

## 3. Conflicts and how they are resolved (my calls)

| Conflict | Resolution |
|---|---|
| Agent Runtime + Memory Bank (01) vs. Cloud Run (03) | **Cloud Run is primary** (URL, IAP, cost). Memory sits behind ADK's memory interface with a SQLite backend; Memory Bank is an optional swap-in, not a dependency. |
| AG-UI + Next.js (06) vs. skip AG-UI (01) | **Build the web UI on AG-UI 1.0 via `ag-ui-adk`** — reviewers don't clone, so a live URL needs a real UI, and AG-UI is the standard way to stream ADK tool calls/subagent activity. |
| LangGraph keyword (01) vs. no rewrite (02, 06) | Optional late phase: a tiny LangGraph client calling the system over **A2A** — one genuine framework boundary, covers both keywords honestly. Cut if time is short. |
| BigQuery mirror (03) | Include as a phase: BigQuery `AI.FORECAST` (TimesFM) is one forecaster in the ledger bake-off, and ADK `BigQueryToolset` in read-only mode. Cheap and on-skill for GCP. |
| Public live demo vs. real-data honesty | Both: public URL runs the synthetic twin; real results appear only as aggregate scorecards and a recorded owner-mode walkthrough. |

## 4. Recommended positioning (one line)

> A personal health agent that **keeps score**: it forecasts how you'll feel,
> grades itself against dumb baselines on your real data, shows a code receipt
> for every number, and publishes the evals — including where it loses.

## 5. Hard dependencies on the owner

1. **Daily journal + overnight wear from now on.** First calibration curve ≈30
   journal days; credible at 60–90. This is the critical path, not the code.
2. Publish the OAuth consent screen to "In Production" (Cloud Console).
3. GitHub: push as `kb2326` (currently inactive `gh` account; git identity is
   "Karth <karth@users.noreply.github.com>").
4. A personal GCP project with billing and a spend cap.

## 6. Cleanup implied

Superseded and to be removed once the new design is approved: the 2026-10-19
spec and plan, `portfolio_stack.md`, `reports/`, the prior
`research_notes/Health agent portfolio revamp/`, `.superpowers/` SDD ledger,
untracked `.agents/` skill copies, branch `revamp/portfolio` (one lint commit —
cherry-pick if useful).
