# Phase 2: Honest Stats + Forecast Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every day the cloud job locks probabilistic forecasts of mood, energy and soreness from six forecasters, hash-chains them, scores matured days against the journal, and publishes the chain hash and an aggregate scoreboard to a public repo.

**Architecture:** A new workspace package `health_ledger` holds the honest-stats layer (source-aware daily values, wear rules, robust baselines, readiness score, corrected associations) and the ledger (feature snapshot, six forecasters, lock, hash chain, scoring, scoreboard, publishing). The existing Cloud Run `sync` job gains three steps after the journal import (lock, score, publish); it stays one job on the existing two schedulers. Ledger rows live in SQLite (append-only, schema v3); after a successful database push the job mirrors new chain entries to a retention-policy bucket and pushes date + chain hash plus the scoreboard to the public repo `kb2326/cha-ledger-log`.

**Tech Stack:** Python 3.13, uv workspace, SQLite, numpy/pandas, `google-genai` (Vertex AI, job service account), `google-cloud-bigquery` (TimesFM via `AI.FORECAST`), git + openssh in the job image (deploy key), Terraform, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-10-20-calibrated-health-agent-design.md` §6.2–6.5, §6.4 in full; `docs/architecture.md` §5–6. Owner decisions 2026-10-23 are recorded under Global Constraints.

## Global Constraints

- Total cloud spend under **$1/month** (budget already $1 with alerts at $0.25, $0.50 and forecast $1). No new always-on resource; no Cloud Build; no new scheduler job (2 of 3 free used).
- Gemini only through **Vertex AI with the job's service account** (`google-genai` with `vertexai=True`); no API key. One Gemini call per locked day; temperature 0; model ID pinned in `Settings.forecast_model`; a model change is a new forecaster ID.
- Ledger bucket: **365-day retention policy, NOT locked** (`is_locked = false`). Locking is a Phase 8 owner step.
- Public repo **`kb2326/cha-ledger-log`**, pushed with a **repo-scoped write deploy key**; private key in Secret Manager secret `ledger-deploy-key`. Public content is **date + chain hash only** plus **aggregate** scoreboard (no per-day scores, lock times, missing-input flags or values).
- Targets: `mood`, `energy`, `soreness`, each a probability distribution over the integers 1..10 (10 probabilities, each ≥ 1e-4 after flooring, summing to 1).
- Forecasters locking from Phase 2: `climatology`, `persistence`, `seasonal_naive`, `statistical`, `timesfm`, `gemini` (forecaster 7 is Phase 3). A forecaster may **abstain** for a day; abstentions are recorded, never silently filled.
- Lock for day D: when last night's sleep for D is present (`daily_metrics` row `sleep`, date D), or at the first run at/after **12:00 owner time** (deadline lock records missing inputs). Never lock a day other than today; one lock per day.
- Scored outcome for D: `journal_outcome` row for D whose submission time is after D's lock; an outcome submitted before the lock voids the day. After D+1 06:00 owner time with no outcome, the day is recorded `no_outcome`.
- **Primary endpoint (pre-registered):** energy, RPS skill vs persistence, with a paired moving-block bootstrap 95% interval (block length 7, 2000 resamples, seed 20261023).
- **HRV is never mixed across sources.** Features read HRV from `FITBIT` only (RMSSD). Resting HR prefers `FITBIT`, falls back to `HEALTH_KIT` only when FITBIT is absent that day.
- **Blinding:** no owner-facing surface (agent tools, CLI) shows a forecast before its day is scored or voided.
- Logs carry counts and IDs only, never health values, journal answers or forecast probabilities.
- Tests use synthetic fixtures only; no network in tests (fakes for BigQuery, Vertex, GCS, git).
- Commit author is the repo-local identity (personal email); push as `kb2326`.

## Review Focus

1. **Two sources on one day** (Fitbit + Apple HRV or RHR): daily value must come from the preferred source, never their mean. → Task 1 `test_hrv_daily_value_never_mixes_sources`.
2. **Job runs twice after the lock is due** (hourly runs 05–12): the second run must not lock again, re-score, or append duplicate chain entries. → Task 9 `test_lock_is_idempotent`, Task 10 `test_scoring_is_idempotent`.
3. **Push to the bucket fails after lock** (concurrent run): nothing may reach the ledger bucket or public repo for entries that are not in the bucket's database. → Task 12 `test_publish_runs_only_after_successful_push`.
4. **Gemini returns malformed JSON or probabilities that don't sum to 1:** the forecaster abstains with a reason; the lock still completes for the others. → Task 8 `test_gemini_bad_output_abstains`.
5. **Journal entry for D submitted before D's lock** (owner journals early, or lock missed until noon): the day is voided, not scored. → Task 10 `test_outcome_before_lock_voids_day`.

---

## File Structure

```
packages/health_data/src/health_data/
  db.py                       MODIFY  _migrate_v3 (ledger tables, daily_metrics.source)
  sync.py                     MODIFY  rebuild_daily honours source preference
config/health.yaml            MODIFY  source_preference per type
packages/health_core/src/health_core/settings.py   MODIFY  ledger settings
packages/health_ledger/       CREATE  new workspace package
  pyproject.toml
  src/health_ledger/
    wear.py          worn/not-worn per day and family
    baselines.py     robust rolling median/MAD, robust z
    readiness.py     open readiness score
    associations.py  detrended lag-0/1 Spearman + Benjamini–Hochberg
    features.py      feature snapshot for day D + canonical hash
    dist.py          distributions, RPS, log score, skill, calibration, bootstrap
    forecasters/
      __init__.py    registry: FORECASTERS, Forecast, Abstain
      baselines.py   climatology, persistence, seasonal_naive
      statistical.py statistical (readiness-conditioned)
      timesfm.py     BigQuery AI.FORECAST
      gemini.py      Vertex AI Gemini
    chain.py         hash chain entries
    lock.py          lock_today
    outcomes.py      score matured days, void, no_outcome
    scoreboard.py    aggregates JSON + static HTML
    publish.py       ledger bucket mirror + public repo push
    cli.py           `cha-ledger` (status, scoreboard, associations)
docs/ledger/analysis-plan.md  CREATE  pre-registration (hashed as genesis entry)
apps/jobs/src/jobs/sync_job.py   MODIFY  lock, score, publish steps
apps/jobs/Dockerfile             MODIFY  git + openssh-client; health_ledger
packages/health_agents/src/health_agents/tools.py  MODIFY  blinding + get_scoreboard
infra/{services,iam,storage,secrets,job,bigquery}.tf   MODIFY/CREATE
tests/test_*.py                  CREATE per task
```

---

### Task 1: Source-aware daily values (schema v3 part 1)

**Files:**
- Modify: `packages/health_data/src/health_data/db.py` (add `_migrate_v3`, append to `MIGRATIONS`)
- Modify: `packages/health_data/src/health_data/sync.py:66` (`rebuild_daily`)
- Modify: `config/health.yaml`
- Test: `tests/test_source_preference.py`, update `tests/test_db_migrate.py`

**Interfaces:**
- Produces: `daily_metrics(date, data_type, agg_value, n_points, source)` with `source TEXT NOT NULL DEFAULT ''`; `sync.source_preference(data_type) -> tuple[str, ...]` reading `CONFIG["data_types"][t].get("sources", ())` (empty = all sources, current behaviour for single-source and roll-up types).
- `config/health.yaml`: `heart-rate-variability` and `daily-heart-rate-variability` get `sources: [FITBIT]`; `daily-resting-heart-rate` gets `sources: [FITBIT, HEALTH_KIT]` (first present wins per day).

- [ ] **Step 1: Write failing tests**

```python
def test_hrv_daily_value_never_mixes_sources(tmpdb):
    # FITBIT 40.0 and HEALTH_KIT 80.0 on the same day -> 40.0, source FITBIT
    ...
    assert row == (40.0, "FITBIT")

def test_rhr_falls_back_to_healthkit_when_fitbit_absent(tmpdb):
    # only HEALTH_KIT 58 on day -> 58, source HEALTH_KIT

def test_types_without_preference_keep_current_behaviour(tmpdb):
    # steps rollup unchanged; source ''

def test_v3_migration_rebuilds_mixed_days(tmp_path):
    # v2 db with a mixed HRV day migrates; daily value becomes FITBIT's
```

- [ ] **Step 2: Run** `uv run pytest tests/test_source_preference.py -v` → FAIL.
- [ ] **Step 3: Implement.** `_migrate_v3` adds the `source` column and calls a rebuild of every type that has a `sources` preference. `rebuild_daily` aggregates per day from the first preferred source that has points that day and stores that source.
- [ ] **Step 4: Run** full suite `uv run pytest -q` → all pass (existing migrate tests updated to expect v3).
- [ ] **Step 5: Commit** `fix(data): daily values from one preferred source; never average RMSSD with SDNN`.

### Task 2: Ledger tables (schema v3 part 2)

**Files:**
- Modify: `packages/health_data/src/health_data/db.py` (`_migrate_v3`, same migration as Task 1)
- Test: `tests/test_ledger_schema.py`

**Interfaces — Produces (exact DDL names; all four `forecasts`, `snapshots`, `ledger`, `scores` are append-only via `BEFORE UPDATE`/`BEFORE DELETE` RAISE(ABORT) triggers):**
- `snapshots(day TEXT PRIMARY KEY, snapshot_json TEXT NOT NULL, snapshot_hash TEXT NOT NULL, locked_at TEXT NOT NULL, missing_json TEXT NOT NULL)`
- `forecasts(id INTEGER PRIMARY KEY, day TEXT NOT NULL, forecaster TEXT NOT NULL, target TEXT NOT NULL CHECK(target IN ('mood','energy','soreness')), probs_json TEXT, abstain_reason TEXT, locked_at TEXT NOT NULL, UNIQUE(day, forecaster, target), CHECK((probs_json IS NULL) <> (abstain_reason IS NULL)))`
- `ledger(seq INTEGER PRIMARY KEY, day TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('plan','lock','outcome','void','no_outcome')), payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, prev_hash TEXT NOT NULL, entry_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, UNIQUE(day, kind))` — the `plan` row uses day `'0000-00-00'`.
- `scores(id INTEGER PRIMARY KEY, day TEXT NOT NULL, forecaster TEXT NOT NULL, target TEXT NOT NULL, outcome INT NOT NULL, rps REAL NOT NULL, log_score REAL NOT NULL, scored_at TEXT NOT NULL, UNIQUE(day, forecaster, target))`
- No "published" bookkeeping table: publish state is read from the destinations (Task 12), so publishing never changes the database.

- [ ] **Step 1: Write failing tests**: `test_ledger_tables_are_append_only` (UPDATE and DELETE on each of the four raise `sqlite3.IntegrityError`), `test_forecast_is_probs_xor_abstain`, `test_one_ledger_entry_per_day_and_kind`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** DDL in `_migrate_v3`. **Step 4: Run** full suite → pass.
- [ ] **Step 5: Commit** `feat(ledger): schema v3 append-only ledger tables`.

### Task 3: Package scaffold, wear rules and robust baselines

**Files:**
- Create: `packages/health_ledger/pyproject.toml` (deps: `health-core`, `health-data`, `numpy`, `pandas`; scripts `cha-ledger = "health_ledger.cli:app"`), `src/health_ledger/__init__.py`, `wear.py`, `baselines.py`
- Modify: root `pyproject.toml` `[tool.uv.sources]` (add `health-ledger = { workspace = true }`), `apps/jobs/pyproject.toml` (depend on `health-ledger`)
- Test: `tests/test_wear.py`, `tests/test_baselines.py`

**Interfaces — Produces:**
- `wear.FAMILIES = ("sleep", "overnight", "day")`
- `wear.worn(conn, day: date) -> dict[str, bool]` with rules (document them in the module docstring verbatim):
  - `sleep`: `sleep` daily value ≥ **180** minutes.
  - `overnight`: a `daily-resting-heart-rate` or FITBIT `daily-heart-rate-variability` value exists for D.
  - `day`: `daily-resting-heart-rate` exists for D **or** `steps` ≥ **1000**.
- `wear.worn_days(conn, family: str, start: date, end: date) -> set[date]`
- `baselines.robust_baseline(values: Sequence[float], min_n: int = 7) -> tuple[float, float] | None` → (median, MAD×1.4826), None if fewer than `min_n` or MAD == 0.
- `baselines.robust_z(x: float, baseline: tuple[float, float]) -> float`
- `baselines.series_before(conn, data_type: str, day: date, family: str, window: int = 28) -> list[float]` → values on worn days in [D−window, D−1].

- [ ] **Step 1: Failing tests**: `test_non_wear_day_is_not_worn_even_with_low_steps` (steps 300, no RHR → day False), `test_short_sleep_not_worn` (150 min), `test_robust_baseline_ignores_one_outlier` (`[60]*10 + [200]` → median 60), `test_baseline_none_below_min_n`, `test_series_before_skips_unworn_days`.
- [ ] **Step 2–4:** run → fail → implement → pass.
- [ ] **Step 5: Commit** `feat(stats): wear rules and robust baselines`.

### Task 4: Open readiness score and corrected associations

**Files:**
- Create: `src/health_ledger/readiness.py`, `src/health_ledger/associations.py`
- Test: `tests/test_readiness.py`, `tests/test_associations.py`

**Interfaces:**
- Consumes: Task 3 `robust_baseline`, `robust_z`, `series_before`.
- Produces: `readiness.score(conn, day: date) -> dict` → `{"score": float | None, "components": {"hrv_z": float|None, "rhr_z": float|None, "sleep_z": float|None}, "n_components": int}`. Score = `clip(50 + 15 * mean(available of [hrv_z, -rhr_z, sleep_z]), 0, 100)`, requires ≥ 2 components else `score None`. HRV = FITBIT `daily-heart-rate-variability`; RHR = `daily-resting-heart-rate`; sleep = `sleep` minutes; all for day D vs `series_before` baselines.
- Produces: `associations.run(conn, targets=("mood","energy","soreness"), lags=(0, 1), min_n=10) -> list[dict]` with keys `metric, target, lag, rho, n, p, q` — Spearman on first-differenced worn-day series vs journal outcomes, Benjamini–Hochberg `q` across all tests in the run; pairs with n < `min_n` omitted. Label: always "association".
- `associations.benjamini_hochberg(p: Sequence[float]) -> list[float]`

- [ ] **Step 1: Failing tests**: `test_readiness_none_with_one_component`, `test_readiness_high_when_hrv_up_rhr_down` (> 50), `test_bh_matches_reference` (p `[0.01, 0.04, 0.03, 0.2]` → q `[0.04, 0.0533…, 0.0533…, 0.2]`), `test_associations_skip_small_n`.
- [ ] **Step 2–4.** **Step 5: Commit** `feat(stats): open readiness score and BH-corrected associations`.

### Task 5: Feature snapshot

**Files:** Create `src/health_ledger/features.py`; Test `tests/test_features.py`

**Interfaces:**
- Consumes: Task 3, Task 4 `readiness.score`.
- Produces: `features.snapshot(conn, day: date) -> tuple[dict, list[str]]` → (snapshot, missing). Snapshot keys (fixed set, `None` when missing; each missing key named in `missing`):
  `day, weekday (0=Mon), sleep_minutes, hrv_rmssd, resting_hr, readiness, steps_prev_day, journal_prev_day {mood,energy,soreness} | None, journal_last7 {target: [values, oldest first]}, journal_days_total`.
  Only data with civil day ≤ D for overnight/sleep values and ≤ D−1 for daytime totals and the journal (no leakage).
- `features.canonical(obj) -> str` = `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`; `features.sha256(text) -> str` (hex).

- [ ] **Step 1: Failing tests**: `test_snapshot_never_reads_journal_for_day_itself`, `test_snapshot_lists_missing_inputs`, `test_canonical_hash_stable_across_key_order`.
- [ ] **Step 2–4.** **Step 5: Commit** `feat(ledger): feature snapshot with no-leakage rule`.

### Task 6: Distributions and scoring math

**Files:** Create `src/health_ledger/dist.py`; Test `tests/test_dist.py`

**Interfaces — Produces (pure functions, numpy only):**
- `Dist = tuple[float, ...]` (length 10, index 0 ↔ score 1)
- `normalize(p: Sequence[float], floor: float = 1e-4) -> Dist` (raises `ValueError` on wrong length, negative or non-finite)
- `from_counts(counts: Sequence[int], prior: float = 1.0) -> Dist` (Dirichlet-smoothed)
- `discretized_normal(mean: float, sd: float) -> Dist` (mass of N(mean, sd) on [k−0.5, k+0.5], tails folded into 1 and 10; sd floored at 0.5)
- `shift(counts_dist: Dist, delta_dist: dict[int, float]) -> Dist` (convolution of a point with a change distribution, clipped to 1..10)
- `rps(p: Dist, outcome: int) -> float` (sum over k=1..9 of (CDF_p(k) − 1[outcome ≤ k])², divided by 9)
- `log_score(p: Dist, outcome: int) -> float` (−ln p[outcome−1])
- `skill(mean_score: float, mean_ref: float) -> float` = `1 − mean_score / mean_ref` (nan if `mean_ref == 0`)
- `block_bootstrap_skill(scores: Sequence[float], ref: Sequence[float], block: int = 7, n: int = 2000, seed: int = 20261023) -> tuple[float, float, float]` (point, lo95, hi95; paired moving blocks)
- `calibration_bins(rows: Sequence[tuple[Dist, int]], bins: int = 5) -> list[dict]` (PIT histogram over randomized PIT, keys `lo, hi, count`)

- [ ] **Step 1: Failing tests**: `test_rps_perfect_is_zero` (one-hot at outcome), `test_rps_uniform_known_value` (uniform, outcome 5 → 0.85 / 9 = 0.0944 to 4 dp), `test_normalize_floors_and_sums_to_one`, `test_discretized_normal_sums_to_one_and_peaks_at_mean`, `test_bootstrap_is_seeded`, `test_skill_negative_when_worse`.
- [ ] **Step 2–4.** **Step 5: Commit** `feat(ledger): distributions, RPS, log score, skill, bootstrap`.

### Task 7: Forecasters 1–4 and the registry

**Files:** Create `src/health_ledger/forecasters/__init__.py`, `baselines.py`, `statistical.py`; Test `tests/test_forecasters_baseline.py`

**Interfaces:**
- Produces (registry in `forecasters/__init__.py`):
  - `@dataclass(frozen=True) class Forecast: probs: dict[str, Dist] | None; abstain: dict[str, str]` (per target, exactly one of a probability or an abstain reason)
  - `Forecaster = Callable[[sqlite3.Connection, date, dict], Forecast]` (conn, day, snapshot)
  - `FORECASTERS: dict[str, Forecaster]` ordered `climatology, persistence, seasonal_naive, statistical, timesfm, gemini` (timesfm and gemini registered by Tasks 8a/8b)
  - `outcome_history(conn, before: date) -> dict[str, list[tuple[date, int]]]` — journal outcomes strictly before D.
- Rules:
  - `climatology`: `from_counts(counts of past outcomes, prior=1.0)`; with zero history it is the uniform prior (never abstains).
  - `persistence`: last outcome within 3 days before D, spread = empirical day-to-day change distribution from history (Dirichlet prior over changes −9..9 with weight 1 on changes −1, 0, +1 until ≥ 10 changes exist); abstain `"no outcome in last 3 days"` otherwise.
  - `seasonal_naive`: outcome on D−7, same spread rule; abstain `"no outcome on D-7"`.
  - `statistical`: ordinary least squares of outcome on readiness over past days with both (≥ 14 pairs), prediction = `discretized_normal(fit, residual sd)`; abstain `"fewer than 14 readiness-outcome pairs"` or `"readiness missing"`.

- [ ] **Step 1: Failing tests**: `test_climatology_uniform_with_no_history`, `test_persistence_centres_on_yesterday`, `test_persistence_abstains_after_gap`, `test_seasonal_uses_same_weekday`, `test_statistical_abstains_below_14_pairs`, `test_no_forecaster_reads_outcome_of_day_itself`.
- [ ] **Step 2–4.** **Step 5: Commit** `feat(ledger): baseline and statistical forecasters`.

### Task 8a: TimesFM forecaster via BigQuery

**Files:** Create `src/health_ledger/forecasters/timesfm.py`; Create `infra/bigquery.tf`; Modify `infra/services.tf`, `infra/iam.tf`, `packages/health_ledger/pyproject.toml` (+`google-cloud-bigquery`), `health_core/settings.py` (+`bq_dataset: str = "cha"`); Test `tests/test_forecaster_timesfm.py`

**Interfaces:**
- Produces: `timesfm.forecast(conn, day, snapshot, *, client=None) -> Forecast`. Builds one in-memory series per target from outcome history (date, value), runs a parameterised query
  `SELECT * FROM AI.FORECAST((SELECT d, v FROM UNNEST(@rows)), data_col => 'v', timestamp_col => 'd', horizon => <days from last outcome to D>, confidence_level => 0.8)` — **no table, no load job** (query over `UNNEST` of a struct array parameter), takes the row for D, maps (`forecast_value`, interval) to `discretized_normal(mean, (upper − lower) / (2 × 1.2816))`.
  Abstains `"fewer than 14 outcomes"` per target, or `"bigquery error: <ExceptionType>"`.
- Terraform: enable `bigquery.googleapis.com`; grant job SA `roles/bigquery.jobUser` on the project. `bigquery.tf` holds a dataset `cha` (location `US`, `default_table_expiration_ms = 2592000000`) reserved for Phase 6; no tables now.
- Cost note in the module docstring: query bytes over parameters are ~0 → inside the 1 TiB free tier.

- [ ] **Step 1: Failing tests** (fake client returning rows): `test_timesfm_maps_interval_to_distribution`, `test_timesfm_abstains_below_14`, `test_timesfm_error_abstains_with_type_only`.
- [ ] **Step 2–4.** Then verify the SQL once against the real project with synthetic numbers: `uv run python -m health_ledger.forecasters.timesfm --selftest` (owner credentials; prints the mapped distribution, no health data). Expected: a 10-value distribution. If `AI.FORECAST` rejects `UNNEST` input, switch to a temporary table with 1-day expiration in dataset `cha` and record the change in the docstring.
- [ ] **Step 5: Commit** `feat(ledger): TimesFM forecaster via BigQuery AI.FORECAST`.

### Task 8b: Gemini forecaster via Vertex AI

**Files:** Create `src/health_ledger/forecasters/gemini.py`; Modify `health_core/settings.py` (+`forecast_model: str = "gemini-3.5-flash-lite"`, +`vertex_location: str = "us-central1"`), `packages/health_ledger/pyproject.toml` (+`google-genai`), `infra/services.tf` (+`aiplatform.googleapis.com`), `infra/iam.tf` (job SA `roles/aiplatform.user`); Test `tests/test_forecaster_gemini.py`

**Interfaces:**
- Produces: `gemini.forecast(conn, day, snapshot, *, client=None) -> Forecast` and `gemini.FORECASTER_ID = f"gemini:{settings.forecast_model}"` (registry key `gemini`, stored forecaster name is `FORECASTER_ID` so a model change is a new forecaster).
- One `generate_content` call, `temperature=0`, `response_mime_type="application/json"`, `response_schema` = object with `mood`, `energy`, `soreness`, each an array of exactly 10 numbers. Prompt = fixed instructions + the canonical snapshot only (same snapshot as every other forecaster; journal note text is never included). Output goes through `dist.normalize`; any failure (exception, bad JSON, wrong length, negative, sum outside 0.9–1.1) → abstain all three with `"gemini: <reason>"`, reason without values.
- Verify the model ID exists on Vertex before committing: `gcloud ai models list` is not for publisher models; instead run `uv run python -m health_ledger.forecasters.gemini --selftest` with owner credentials against a synthetic snapshot. If `gemini-3.5-flash-lite` is not served on Vertex in `us-central1`, use the current Flash-Lite ID that is, and set it as the default.

- [ ] **Step 1: Failing tests** with a fake client: `test_gemini_parses_three_distributions`, `test_gemini_bad_output_abstains` (sum 3.0; wrong length; invalid JSON), `test_gemini_prompt_contains_snapshot_only` (no `note` field, no forecasts of others).
- [ ] **Step 2–4**, self-test. **Step 5: Commit** `feat(ledger): Gemini forecaster on Vertex AI`.

### Task 9: Hash chain and the lock

**Files:** Create `src/health_ledger/chain.py`, `src/health_ledger/lock.py`, `docs/ledger/analysis-plan.md`; Test `tests/test_chain.py`, `tests/test_lock.py`

**Interfaces:**
- `chain.GENESIS_PREV = "0" * 64`
- `chain.append(conn, day: str, kind: str, payload: dict) -> str` — `payload_hash = sha256(canonical(payload))`, `entry_hash = sha256(prev_hash + "|" + day + "|" + kind + "|" + payload_hash)`, `prev_hash` = latest `entry_hash` or `GENESIS_PREV`; inserts into `ledger`; returns `entry_hash`.
- `chain.verify(conn) -> list[str]` — empty when every row's hashes recompute and link; otherwise one message per broken seq.
- `Settings.analysis_plan_path: Path = Path("docs/ledger/analysis-plan.md")` (job image sets `CHA_ANALYSIS_PLAN_PATH=/app/docs/ledger/analysis-plan.md`; `.dockerignore` gains `!docs/ledger` after `docs`, and the Dockerfile copies `docs/ledger`).
- `chain.ensure_plan(conn, plan_path: Path) -> None` — appends the `plan` entry (payload `{"analysis_plan_sha256": sha256(file bytes)}`) if absent.
- `lock.due(conn, now: datetime) -> bool` — today (owner zone) not locked and (sleep for today present or local time ≥ 12:00).
- `lock.lock_today(conn, now: datetime, forecasters: Mapping[str, Forecaster] = FORECASTERS) -> dict | None` — if not `due`, returns None. Else: snapshot (Task 5), insert `snapshots`, run every forecaster (a forecaster that raises abstains all targets with `"error: <ExceptionType>"`), insert `forecasts`, append chain `lock` entry with payload `{"snapshot_hash", "forecasts_hash"}` (hash of canonical list of forecast rows), all in **one transaction**. Returns counts `{"forecasters": n, "abstained": k, "missing_inputs": m}`.
- `docs/ledger/analysis-plan.md`: forecaster definitions (Task 7–8b rules), targets, lock and outcome windows, primary endpoint and bootstrap parameters from Global Constraints, secondary endpoints (mood, soreness RPS skill vs persistence and climatology; log scores; calibration bins), the honesty rule (published as-is, real n shown), and that forecaster 7 joins in Phase 3 as a pre-registered secondary hypothesis (6 vs 7).

- [ ] **Step 1: Failing tests**: `test_chain_verify_detects_edited_payload` (copy rows into a scratch table with altered payload_hash → `verify` reports it), `test_chain_links_prev_hash`, `test_lock_due_on_sleep_or_noon` (09:00 with sleep → True; 09:00 no sleep → False; 12:00 no sleep → True), `test_lock_is_idempotent` (second call returns None; row counts unchanged), `test_forecaster_exception_abstains_not_crashes`, `test_lock_is_atomic` (forecasts insert failure → no snapshot, no ledger row).
- [ ] **Step 2–4.** **Step 5: Commit** `feat(ledger): hash chain, pre-registered plan, daily lock`.

### Task 10: Scoring matured days

**Files:** Create `src/health_ledger/outcomes.py`; Test `tests/test_outcomes.py`

**Interfaces:**
- Consumes: Task 2 tables, Task 6 `rps`, `log_score`, Task 9 `chain.append`.
- Produces: `outcomes.settle(conn, now: datetime) -> dict` → counts `{"scored": a, "voided": b, "no_outcome": c}`. For each locked day D with no `outcome`/`void`/`no_outcome` ledger entry:
  - outcome row exists in `journal_outcome` and its submission `submitted_at` > `snapshots.locked_at` → insert `scores` for each non-abstained forecast and target; chain `outcome` entry payload `{"outcome_row_hash": <journal_submissions.row_hash>, "scores_hash": sha256(canonical(score rows))}`.
  - outcome submitted ≤ lock time → chain `void` entry `{"reason": "journal before lock"}`.
  - no outcome and now ≥ D+1 06:00 owner time → chain `no_outcome` entry `{}`.
  - otherwise leave unsettled. One transaction per day.

- [ ] **Step 1: Failing tests**: `test_scores_written_for_each_forecaster_and_target`, `test_outcome_before_lock_voids_day`, `test_no_outcome_after_deadline`, `test_unsettled_before_deadline`, `test_scoring_is_idempotent`, `test_abstained_forecasts_not_scored`.
- [ ] **Step 2–4.** **Step 5: Commit** `feat(ledger): settle matured days into scores, voids and misses`.

### Task 11: Scoreboard

**Files:** Create `src/health_ledger/scoreboard.py`; Test `tests/test_scoreboard.py`

**Interfaces:**
- Produces: `scoreboard.build(conn) -> dict` — `{"generated_at", "days_locked", "days_scored", "days_voided", "days_no_outcome", "primary": {"target": "energy", "forecaster": <best non-persistence by mean RPS or null>, "skill_vs_persistence": [point, lo, hi] | null, "n": int}, "forecasters": [{"id", "target", "n", "mean_rps", "skill_vs_climatology", "skill_vs_persistence"}], "calibration": {forecaster: {target: bins}}}`. Skill vs a reference uses only days both scored (paired). Aggregates only.
- `scoreboard.render_html(board: dict) -> str` — one self-contained static page (inline CSS, no scripts, both colour schemes via `prefers-color-scheme`), states "n" next to every number and the honesty rule text.
- Primary skill CI computed only when n ≥ 10, else null with `"n below 10"` shown.

- [ ] **Step 1: Failing tests**: `test_board_contains_no_per_day_values` (no ISO date other than `generated_at`; no key `day`), `test_skill_is_paired`, `test_primary_null_below_10`, `test_html_shows_n`.
- [ ] **Step 2–4.** **Step 5: Commit** `feat(ledger): aggregate scoreboard JSON and static page`.

### Task 12: Publishing (ledger bucket + public repo)

**Files:** Create `src/health_ledger/publish.py`; Modify `infra/storage.tf` (ledger bucket), `infra/secrets.tf` (`ledger-deploy-key`), `infra/iam.tf`, `infra/job.tf` (env `CHA_LEDGER_BUCKET`, `CHA_LEDGER_REPO=git@github.com:kb2326/cha-ledger-log.git`, `CHA_LEDGER_KEY_SECRET=ledger-deploy-key`), `health_core/settings.py` (+`ledger_bucket`, `ledger_repo`, `ledger_key_secret`, all `str | None = None`), `apps/jobs/Dockerfile` (`apt-get install -y --no-install-recommends git openssh-client`); Test `tests/test_publish.py`

**Interfaces:**
- `publish.to_bucket(conn, bucket: str, *, client=None) -> int` — lists existing `ledger/` object names once, uploads each missing ledger row as `ledger/<seq:06d>-<day>-<kind>.json` (full row, private bucket) with `if_generation_match=0` (never overwrite; a precondition failure counts as already published). Returns count uploaded.
- `publish.to_repo(conn, repo_url: str, key_pem: str, board: dict, *, git=run_git) -> int` — clone depth 1 into a temp dir using `GIT_SSH_COMMAND="ssh -i <tmpkey> -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=<pinned github.com ed25519 key file>"`; read the dates already in `chain.csv` (header `date,chain_hash`) and append one line per day not yet present = that day's latest `entry_hash` (the plan entry's line uses date `plan`; a day is appended only once it is settled or past D+1 06:00, so a line never changes); write `docs/scoreboard.json` and `docs/index.html`; commit as `cha-ledger-bot <noreply@users.noreply.github.com>` and push. No-op (returns 0, no push) when nothing is new and the board is unchanged. Key file written with mode 0600 and deleted in `finally`.
- Terraform: bucket `${project}-ledger` (`US-CENTRAL1`, uniform access, public access prevention enforced, `retention_policy { retention_period = 31536000, is_locked = false }`, no versioning); job SA `roles/storage.objectCreator` + `roles/storage.objectViewer` on it (no delete); secret container `ledger-deploy-key` + accessor for job SA.

- [ ] **Step 1: Failing tests** (fake bucket, fake git recording commands): `test_bucket_mirror_never_overwrites` (existing object → skipped, precondition failure → counted as published), `test_repo_publishes_date_and_hash_only` (chain.csv lines match `^(plan|\d{4}-\d\d-\d\d),[0-9a-f]{64}$`), `test_repo_skips_dates_already_in_chain_csv`, `test_repo_noop_when_nothing_new`, `test_key_file_removed_after_push`, `test_publish_runs_only_after_successful_push` (lives in Task 13's job tests; listed here for the reviewer).
- [ ] **Step 2–4.** **Step 5: Commit** `feat(ledger): mirror chain to retention bucket and public log`.

### Task 13: Job integration, blinding and the CLI

**Files:** Modify `apps/jobs/src/jobs/sync_job.py`, `packages/health_agents/src/health_agents/tools.py`; Create `src/health_ledger/cli.py`; Test `tests/test_sync_job.py`, `tests/test_blinding.py`, `tests/test_ledger_cli.py`

**Interfaces:**
- Job step order: `pull, migrate, sync, journal, lock, settle, push, publish, heartbeat`.
  - `lock` and `settle` run when pull and migrate succeeded and the sync error is not a `DatabaseError` (auth failure still locks: the lock records missing inputs). `lock` calls `chain.ensure_plan` first (plan file shipped in the image at `/app/docs/ledger/analysis-plan.md`, path from `Settings.analysis_plan_path`).
  - Ledger rows written by `lock`/`settle` count as changed data for the push rule (`changed_rows` += rows written).
  - `publish` runs only when the push succeeded **or** was skipped because nothing changed (then it retries anything the destinations are missing), never after a failed or skipped-for-error push; its failure fails the run (alert) but never blocks the heartbeat. Publishing does not write to the database.
  - Heartbeat gains `"locked_today": bool`.
- Blinding: `tools.run_sql` rejects any statement referencing `forecasts`, `snapshots`, `scores` or `ledger` (case-insensitive, after comment stripping) with an explanation; new tool `get_scoreboard() -> dict` returns `scoreboard.build(conn)` (aggregates over settled days only). Agent instructions in `agent.py` mention it.
- CLI `cha-ledger`: `status` (days locked/scored/voided, chain verify result, no probabilities), `scoreboard` (prints JSON), `associations` (prints the Task 4 table), `verify` (exit 1 on a broken chain).

- [ ] **Step 1: Failing tests**: job order test, `test_publish_runs_only_after_successful_push`, `test_auth_failure_still_locks`, `test_database_error_skips_ledger`, `test_ledger_rows_trigger_push`, `test_run_sql_blocks_ledger_tables` (also `SELECT * FROM "Forecasts"` and a comment-smuggled variant), `test_get_scoreboard_has_no_unsettled_days`, `test_cli_status_prints_no_probabilities`.
- [ ] **Step 2–4.** **Step 5: Commit** `feat(job): lock, settle and publish in the daily job; blind the agent`.

### Task 14: Deploy, genesis and first lock (owner-approved cloud steps)

**Files:** Modify `infra/*.tf` (from Tasks 8a, 8b, 12), `infra/terraform.tfvars` (gitignored: `job_image`), `infra/README.md` (ledger runbook: deploy key rotation, verifying the chain, retention lock at Phase 8)

- [ ] **Step 1: Public repo + deploy key.** `GH_TOKEN=$(gh auth token --user kb2326) gh repo create kb2326/cha-ledger-log --public --description "Hash log of the Calibrated Health Agent forecast ledger: date + chain hash only" --add-readme`; generate `ssh-keygen -t ed25519 -N "" -C cha-ledger-bot -f <scratchpad>/ledger_key`; add the public key as a **write** deploy key (`gh repo deploy-key add ... --allow-write`); push the private key to Secret Manager `ledger-deploy-key` (after Terraform creates the container); delete the local key files. Enable Pages from `main` `/docs` via `gh api -X POST repos/kb2326/cha-ledger-log/pages`.
- [ ] **Step 2: Build and push image** tag = commit SHA; local synthetic smoke run passes (`CHA_DATA_MODE=synthetic`).
- [ ] **Step 3: `terraform plan`**: expected adds = ledger bucket, its 2 IAM members, secret container + accessor, BigQuery dataset, 2 service enables, 2 project IAM members; changes = job (image, env). Nothing destroyed. Apply.
- [ ] **Step 4: Run the job** (`gcloud run jobs execute sync --region us-central1 --wait`). Expected logs: `lock` INFO with counts (or "not due"), `publish` INFO; heartbeat ok. `cha-ledger verify` on a pulled copy → exit 0. Public repo shows `chain.csv` with the `plan` line and today's line; Pages URL serves the scoreboard.
- [ ] **Step 5: Cost check.** `gcloud billing` budget unchanged; note expected monthly cost lines in `docs/cloud-design.md` (Gemini Flash-Lite ≈ 30 calls/month, BigQuery queries ≈ 0 bytes billed, ledger bucket < 1 MB). Must remain under $1.
- [ ] **Step 6: Commit** `infra: ledger bucket, Vertex and BigQuery access, deploy-key secret` and merge to `main`, push.

### Task 15: Docs and the explainer

**Files:** Modify `README.md` (status table: Phase 2 live; cost line $1 budget; links to public log and scoreboard), `docs/architecture.md` (§5.1 tables now real, wear rules, source preference), `docs/cloud-design.md` (ledger bucket, Vertex, BigQuery, publishing), `.notes/project-explainer.html` (republish to the same artifact URL: Phase 2 chips → Live, change log)

- [ ] **Step 1:** Update the four documents; README must still mark Phase 3+ items as planned.
- [ ] **Step 2:** `uv run pytest -q && uv run ruff check . && uv run pyright` → all green.
- [ ] **Step 3: Commit** `docs: phase 2 live — ledger, scoreboard, public hash log` and push.

---

## Deferred (recorded so nothing is silently dropped)

- Rolling-origin backtest panel and adaptive conformal intervals: Phase 3, when forecaster 7 joins and backtests matter.
- BigQuery mirror of daily tables: Phase 6 (TimesFM here queries parameters directly, so no mirror is needed now).
- Retention lock on the ledger bucket: Phase 8 owner step.

## Exit check (from the spec)

The ledger has locked, hash-chained forecasts every day; scoring runs on matured days; `cha-ledger verify` passes; the public log shows one line per locked day; spend stays under $1/month.
