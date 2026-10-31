# Phase 4.5 Capable Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the rigid agent into a modern, capable one over all the owner's data (detail, new types, weather) and prove it on the owner's 110 labelled questions.

**Architecture:** One Gemini agent in an ADK tool loop with thinking on, discovering data through a catalog tool and computing in SQL or the sandbox. Specialists become optional `AgentTool`s. A smarter, quieter grounding check. A schema v5 data layer derived from `raw_points.raw_json`, 13 more API types, and Open-Meteo weather for Erode.

**Tech Stack:** Python 3.13, google-adk 2.12 (`BuiltInPlanner`, `AgentTool`), SQLite, Open-Meteo (archive + forecast, no key), pytest.

**Spec:** `docs/superpowers/specs/2026-10-31-phase-4-5-capable-agent-design.md`. Research: `docs/research/11-google-health-api-catalog.md`.

## Global Constraints

- **Ledger frozen.** The forecast ledger, its features and `docs/ledger/analysis-plan.md` are not changed. Existing `daily_metrics` values (for example `sleep` = time in bed) stay as they are; corrected measures are **added** in new tables or metrics.
- **Same guarantees:**
  - every number comes from code with a receipt;
  - data access is read-only;
  - untrusted text is wrapped;
  - the only outbound call is weather, with coordinates from trusted context (settings or the front end), never from the model;
  - no diagnosis; red flags are escalated.
- **No new OAuth scopes:** no nutrition, hydration, ECG or IRN (owner, 2026-10-31).
- **Home location:** Erode, latitude 11.3410, longitude 77.7172, timezone Asia/Kolkata. Phase 5 passes live location.
- **Cost:** cloud steady state under $1/month; the owner allowed $2–3 of Vertex for today's eval runs.
- **No real data in the repo, CI or fixtures.** Real transcripts stay under `data/evals/`.

## Review Focus

1. **A day with partial data** (sleep present, steps missing) → the agent computes on what exists and names the gap; it never refuses. → Task 6 case `cap-partial-*`.
2. **Weather fetch fails** (offline, or HTTP 5xx) → the tool returns an error the agent explains; the sync job logs it without failing the run. → Task 3 `test_weather_failure_is_soft`.
3. **raw_json with missing sub-fields** (no stages, a nap) → the derive step skips that field, never crashes, and never invents values. → Task 2 `test_derive_tolerates_missing_fields`.
4. **The model passes its own location to the weather tool** → ignored: the tool schema has no location argument. → Task 4 `test_weather_tool_has_no_location_argument`.
5. **An old database without the v5 tables** (laptop not migrated) → `data_catalog` lists only what exists, and the agent says the detail isn't synced yet. → Task 4 `test_catalog_on_v4_database`.

---

### Task 1: Sync the 13 additional API types

**Files:** Modify `config/health.yaml`, `packages/health_data/src/health_data/client.py` (TIME_FIELD, ROLLUP_TYPES, VALUE_FIELD, rollup extraction), `sync.py` (PROBE_CANDIDATES); Test `tests/test_client_new_types.py`

**Types:**
- **sample:** vo2-max, run-vo2-max, body-fat, height, blood-glucose, core-body-temperature;
- **daily:** daily-heart-rate-zones (thresholds, raw_json only);
- **interval list:** active-energy-burned (sum kcal), activity-level (raw only, timeline), altitude (sum m), swim-lengths-data (sum strokes);
- **rollup:** calories-in-heart-rate-zone (sum kcal);
- **v4beta, list on demand only:** skin-temperature-sensors (Pixel Watch 4/5; not in config).

**Tests:** filter paths per kind; value extraction from documented shapes (vo2Max, percentage → body-fat %, heightMillimeters → m, bloodGlucoseMilligramsPerDeciliter, temperatureCelsius, kcal, gainMillimeters → m, strokeCount); calories-in-zone rollup sum.

**Commit:** `feat(data): sync 13 more Google Health API types`

### Task 2: Schema v5 detail tables derived from raw_json

**Files:** Modify `packages/health_data/src/health_data/db.py` (SCHEMA_VERSION 5, migration); Create `packages/health_data/src/health_data/derive.py`; Modify `apps/jobs/src/jobs/sync_job.py` (a `derive` step after sync), `health_data/cli.py` (`cha-data db derive`); Test `tests/test_derive.py`

**Tables** (rebuilt idempotently: delete + insert inside one transaction):
- `sleep_sessions(date, start, end, main_sleep, minutes_asleep, minutes_awake, minutes_to_fall_asleep, minutes_in_period, deep_min, light_min, rem_min, awake_min, efficiency)`, where date is the civil date of the end;
- `exercise_sessions(date, start, type, name, active_min, calories_kcal, distance_km, steps, avg_hr_bpm, azm, light_min, moderate_min, vigorous_min, peak_min)`;
- `night_vitals(date, skin_temp_c, skin_temp_baseline_c, skin_temp_delta_c, spo2_avg, spo2_low, spo2_high, hrv_ms, hrv_deep_ms, non_rem_hr_bpm, resp_full, resp_deep, resp_light, resp_rem)`;
- `activity_breakdown(date, fat_burn_azm, cardio_azm, peak_azm, light_active_min, moderate_active_min, vigorous_active_min, zone_light_min, zone_moderate_min, zone_vigorous_min, zone_peak_min)`;
- `hr_zone_thresholds(date, zone, min_bpm, max_bpm)`.

**Tests:** each table from synthetic raw_json in the shapes recorded in research 11 and the 2026-10-31 inspection; `test_derive_tolerates_missing_fields`; `test_derive_is_idempotent`; `test_migration_v4_to_v5_keeps_data`; the ledger tables are untouched.

**Commit:** `feat(data): schema v5 detail tables for sleep stages, workouts, night vitals and zones`

### Task 3: Weather for Erode

**Files:** Create `packages/health_data/src/health_data/weather.py`; Modify `db.py` (`weather_daily(date, temp_min_c, temp_max_c, temp_mean_c, humidity_mean, precipitation_mm, uv_index_max, sunrise, sunset, source)` in v5), `health_core/settings.py` (`home_latitude=11.3410`, `home_longitude=77.7172`, `home_place="Erode"`), `sync_job.py` (a `weather` step: the last 7 days plus a backfill when empty), `health_data/cli.py` (`cha-data weather backfill --since`); Test `tests/test_weather.py`

- **Open-Meteo archive** (`archive-api.open-meteo.com/v1/archive`) for history; **forecast** (`api.open-meteo.com/v1/forecast`) for the recent days and the next 7.
- Coordinates come from settings only. A timeout of 15 s.
- **Soft failure:** a weather error never fails the run; it logs `weather` ERROR with the type only.

**Tests:** parse a recorded response; upsert is idempotent; `test_weather_failure_is_soft`; the request URL contains only the settings coordinates and dates.

**Commit:** `feat(data): daily weather for the home location from Open-Meteo`

### Task 4: Agent tools: data catalog, query_metric, weather; access to the new tables

**Files:** Modify `packages/health_agents/src/health_agents/tools.py`, `sqlguard.py` (ALLOWED_TABLES adds the v5 tables and weather_daily), `bundle.py` (adds detail tables and weather frames), `workflow.py` (ALL_TOOLS); Test `tests/test_agent_tools_v5.py`

- `data_catalog() -> dict`: for every daily metric and every detail table, the description, unit, granularity, first and last date, days covered in the last 30/90 days, and gaps; built from live tables plus a static description map. On a v4 database it lists only what exists.
- `query_metric(metric: str, start: str, end: str, agg: Literal["daily","mean","min","max","sum","count"] = "daily") -> dict` with a receipt. Metric names cover daily_metrics types plus derived columns (`sleep.minutes_asleep`, `sleep.deep_min`, `night.spo2_low`, `weather.temp_max_c` and so on).
- `weather(days_ahead: int = 0, days_back: int = 0) -> dict`: the forecast or recent weather for the **session location** (the trusted context key `location`, else settings home), with a receipt. **No location argument.**

**Tests:** `test_catalog_lists_detail_tables_and_coverage`, `test_catalog_on_v4_database`, `test_query_metric_derived_column_with_receipt`, `test_weather_tool_has_no_location_argument`, `test_weather_tool_uses_session_location`, `test_sql_allows_new_tables_and_still_blinds_ledger`.

**Commit:** `feat(agents): data catalog, query_metric and weather tools over the full data layer`

### Task 5: Modern agent architecture

**Files:** Modify `workflow.py`, `instructions.py`, `verify.py`, `cli.py`; Test `tests/test_workflow.py`, `tests/test_verify.py`

- **Single topology:** `LlmAgent` with `planner=BuiltInPlanner(thinking_config=ThinkingConfig(thinking_budget=settings.agent_thinking_budget))` (default 1024) and every tool.
- **multi topology → `team`:** the same main agent, plus `AgentTool(coach)` and `AgentTool(domain_expert)`, each specialist with read-only tools. The router, dispatch, collect and synthesize nodes are removed. `CHA_TOPOLOGY=multi` stays accepted as an alias.
- **verify_receipts:** the retry always goes to the main agent (which has tools). `numbers_without_receipts` gains question-implied numbers (window phrases → 7/14/28/30/31/90/365, day counts between dates in the answer, the number of dates listed), and after one retry a quiet note `_Note: 1 figure wasn't computed by a tool: X._` instead of the `unverified:` footer. Graders accept both, and the `no_unverified` check looks for the note.
- **Instructions rewrite (helpful-first):** discover with `data_catalog` first; compute on the available days and state any gaps; use the detail tables for sleep and workouts; give practical wellness guidance; never diagnose or dose; escalate red flags; no scolding disclaimers.

**Tests:**
- existing workflow tests ported;
- `test_team_topology_delegates_to_coach_tool`;
- `test_retry_goes_to_agent_with_tools`;
- `test_window_phrases_are_backed` ("last month … 30 days");
- `test_quiet_note_replaces_footer`;
- `test_thinking_planner_configured`.

**Commit:** `feat(agents): single tool-loop agent with thinking, specialists as tools, calmer grounding`

### Task 6: Realistic fixture and new cases

**Files:** Modify `packages/health_agents/src/health_agents/smoke.py` (fixture: all synced types, raw_json for sleep/exercise/vitals/zones, derived tables, weather), `packages/health_eval/src/health_eval/fixture.py`, `evals/cases/*.yaml` (truth SQL still valid; new capability and regression cases for stages, sessions, night vitals, weather, partial-data comparisons, `cap-partial-*`), `evals/questions/grid.yaml` (metrics per data state); Test: the suites and fixture tests updated

**Commit:** `feat(eval): realistic fixture with every data type, detail tables and weather; new cases`

### Task 7: Re-run and compare (Vertex)

- Re-run the owner's 110 questions (single and team) on the new fixture, plus the 20 real-data questions.
- Re-run the regression, safety and red-team suites and the ablation (team vs single, thinking on vs off).
- Compare old against new per labelled question with a blind pairwise judge. Report the fixed / still failing / newly failing counts and before/after suite rates.

**Output:** `docs/evals/results/2026-10-31-phase-4-5.md` (aggregates only).

**Commit:** `docs(evals): before and after Phase 4.5 on the owner's labelled questions`

### Task 8: Docs, final review, deploy and merge

- **ADRs:** 0007 (agent architecture), 0008 (data layer v5 and weather), 0005 updated (single vs team).
- Update the threat model (the weather outbound call), system card, README, observability, and the explainer artifact.
- Final review (opus); fix pass.
- **Owner's yes:**
  1. deploy the job image (derive and weather steps);
  2. CI gate proof (control passes, break fails);
  3. merge.
