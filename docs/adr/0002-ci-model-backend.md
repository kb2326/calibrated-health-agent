# ADR 0002 — Model backend for CI and synthetic evals

**Status:** accepted in principle, 2026-10-30; free-tier facts pending (see "Open").

## Context

Evals in CI and nightly runs need a model. The budget is under $1/month and the parent spec
allows a **free-tier Gemini key for synthetic data only** (free-tier traffic may be used to
improve Google products, so the owner's real health data never goes through it). The agent
reaches Gemini through ADK, which reads `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT`,
`GOOGLE_CLOUD_LOCATION` or `GOOGLE_API_KEY` from the environment.

## Decision

- CI sets `GOOGLE_GENAI_USE_VERTEXAI=false` and `GOOGLE_API_KEY` from the repository secret
  `GEMINI_API_KEY`, with `CHA_DATA_MODE=synthetic`. `health_agents.vertex.configure()` only sets
  defaults, so existing env wins (pinned by `tests/test_backend_switch.py`); no Phase 3 code
  changes.
- The key must be a **free-tier** key: created in AI Studio in a Google Cloud project **without
  billing**. A key created in `artful-timing-506108-n8` (billing on) is paid tier and is not
  used for CI.
- The job and the owner's laptop keep Vertex AI under `artful-timing-506108-n8`.

## Open (filled when the free-tier key exists)

- Model served on the free tier: `gemini-3.5-flash-lite` — **confirmed 2026-10-30**: one
  synthetic smoke question answered with a receipt on a key from project
  `my-demo-projects-for-credits` (AI Studio shows "Free tier"; its billing account is closed,
  so nothing can be charged). No `Settings.eval_model` is needed.
- Free-tier limits for that model (AI Studio, 2026-10-30): **15 RPM**, **250K TPM**, **500 RPD**. One agent question costs about 3–6 model requests (answer, tool rounds, at most
  one verify retry), so CI paces cases to stay under 15 requests a minute.
- PR suite size: regression × 2 (retry worst case) must fit the daily limit; otherwise PRs run
  the `must_pass` subset and the nightly job runs the rest. At 500 RPD and up to 6 requests a
  question, a day holds about 80 questions. Budget: a PR run is capped at **30 cases**
  (≤ 180 requests, ≤ 360 with one full retry), leaving the rest of the day for one nightly run;
  everything beyond the cap runs nightly.

## Consequences

CI costs $0. Free-tier rate limits bound how many cases run per PR; quota exhaustion shows as
`NOT_EVALUATED` and fails the gate with the reason, never as a silent pass.
