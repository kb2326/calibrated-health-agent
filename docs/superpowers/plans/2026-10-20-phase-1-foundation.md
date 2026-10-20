# Phase 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the new `kb2326/calibrated-health-agent` repository with the carried-over read-only harness, pure and complete data ingestion (daily rollups verified against reconcile, extra scopes and types, full backfill, append-only journal import), a free-tier GCP slice that syncs daily without the owner's laptop and alerts on failure, and ADK 2.12 with explicit delegation.

**Architecture:** A uv workspace monorepo. `health_core` holds settings; `health_data` holds the API client, storage, sync, journal import and GCS persistence; `health_agents` holds the ADK agent. A single Cloud Run job (`sync`) pulls the SQLite file from a private GCS bucket, syncs from the Google Health API and the journal Sheet, and pushes it back with a generation precondition; Cloud Scheduler triggers it. All infra is Terraform.

**Tech Stack:** Python 3.13, uv, ruff, pyright, pytest, pydantic-settings, Typer, google-api-python-client, google-cloud-storage, google-cloud-secret-manager, google-adk 2.12.0, Docker, Terraform ≥1.16, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-20-calibrated-health-agent-design.md` · **Architecture:** `docs/architecture.md`

**Revision:** 2026-10-20, after an independent go/no-go review (verdict: go with changes) — daily-only main DB with a 50 MB cap and reconcile parity check; append-only journal submissions with outcome windows; GCS as source of truth; failure alerting; Terraform and image fixes; ADK task moved off the critical path.

## Global Constraints

- Read-only toward the Google Health API: no method outside `READ_METHODS` may be dispatched; only `.readonly` scopes requested.
- GCP project `artful-timing-506108-n8`, region `us-central1`, billing account `01DA8F-C0DAA3-A37763`.
- Spend under $5/month: budget alerts at $2 and $4; Cloud Run jobs only (no always-on services in this phase); Artifact Registry cleanup keeps the 3 newest images.
- Owner time zone `Asia/Kolkata` for civil days and schedules.
- Commits authored `Karthick Balaje Gopalakrishnan Elango <karthickbalaje01@gmail.com>`; repo `kb2326/calibrated-health-agent`, **private** in this phase.
- Never commit: `data/`, `config/*.json`, tokens, `.env`, real-data values. Research notes are scrubbed of personal facts before they enter the repo.
- Python 3.13; `uv run` for every command; settings env prefix `CHA_`.
- SQLite is never written through a FUSE mount; GCS writes use `if_generation_match`. **GCS is the source of truth**: local commands that write must pull first.
- The main SQLite holds **daily** values and raw daily/session points only; it must stay under **50 MB** (enforced by a test). Minute-level streams are never stored in it.
- Journal data is **append-only**: every submission is kept with a row hash; nothing overwrites an earlier submission.
- Cloud Run job memory 2 GiB (local disk is in-memory); images contain only the `jobs` package and its deps (no ADK), built locally and pushed — **no Cloud Build** (its staging bucket is outside the free tier).
- Failures must alert: a failed job execution emails the owner (log-based alert, free).
- Existing 49 tests keep passing after the move (renamed imports only).

## Review Focus

1. **API throttling or failure mid-backfill** (429/5xx after retries): the run stops with a non-zero exit, cursors for completed types are kept, and a rerun resumes without duplicate rows. → test in Task 5.
2. **Two job runs overlapping** (scheduler retry while a run is in flight): the second push fails on the generation precondition and exits non-zero without overwriting newer data. → test in Task 7.
3. **Journal edge cases**: values outside 1–10 or a malformed date are stored as `invalid` with a reason and never become outcomes; a submission after midnight IST but before 06:00 belongs to the date the owner entered. → tests in Task 6.
4. **Revoked or expired refresh token in the cloud**: the job fails loudly with an error naming re-login, never exits 0 having synced nothing. → test in Task 8.
5. **A data type the device doesn't emit**: sync records zero points and moves on; one failing type does not abort the others. → test in Task 4.
6. **A journal row edited or resubmitted after the fact** (Sheet edit, backdated Form entry): the original submission stays, the change is stored as a new flagged submission, and the day's outcome is the first submission inside its window. → tests in Task 6.
7. **Local and cloud DB drift**: a local write command run without a fresh pull refuses to run. → test in Task 7.

---

## Execution order

T1 → T2 → T3 → **T6 (journal, brought forward so journal days start counting)** → T4 → T5 → T7 → T8 → T9 → T10 → T11 → T12. T6 depends only on T1 and T3.

## File structure

```
calibrated-health-agent/
  pyproject.toml                       uv workspace root, ruff, pyright, pytest config
  README.md  LICENSE  .gitignore  .pre-commit-config.yaml
  config/health.yaml                   tracked types, scopes, thresholds (no secrets)
  docs/architecture.md  docs/superpowers/{specs,plans}/  docs/research/  (scrubbed)
  packages/health_core/src/health_core/settings.py
  packages/health_data/src/health_data/
      client.py auth.py db.py sync.py obs.py journal.py      (carried over, path-fixed)
      reconcile.py        reconciled fetch for summed types
      backfill.py         full-history backfill
      journal_import.py   Google Sheet → journal
      store.py            GCS pull/push with generation precondition
      secrets.py          Secret Manager token access
      cli.py              `cha-data` Typer app
      legacy/analyze.py correlate.py learn.py digest.py      (replaced in Phase 2)
  packages/health_agents/src/health_agents/agent.py tools.py api_tools.py
  apps/jobs/src/jobs/sync_job.py       Cloud Run job entrypoint
  apps/jobs/Dockerfile
  infra/                               Terraform (backend, services, budget, bucket, secrets, AR, SA, job, scheduler)
  evals/health_agent_core.evalset.json
  tests/                               carried-over tests + new tests per task
  .github/workflows/ci.yml
```

Local paths: new repo at `C:\Users\karth\calibrated-health-agent`; the old folder `C:\Users\karth\Google Health Agent` is the source to copy from and stays as an archive.

---

### Task 1: Bootstrap the repository and carry over the harness

**Files:**
- Create: `pyproject.toml`, `packages/*/pyproject.toml`, `packages/health_core/src/health_core/settings.py`, `.gitignore`, `LICENSE`, `.pre-commit-config.yaml`
- Move (copy from old folder, then edit imports/paths): `scripts/{client,auth,db,sync,obs,journal}.py` → `packages/health_data/src/health_data/`; `scripts/{analyze,correlate,learn,digest}.py` → `packages/health_data/src/health_data/legacy/`; `health_agent/*.py` → `packages/health_agents/src/health_agents/`; `tests/*.py`, `evals/`, `config/health.yaml`, `README.md`, `docs/` (spec, architecture, plans)
- Create: `docs/research/` from `research_notes/2026-10-20-deep/` with personal facts removed
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `health_core.settings.Settings` (pydantic-settings, env prefix `CHA_`) with fields `data_mode: Literal["real","synthetic"] = "real"`, `data_dir: Path = Path("data")`, `config_dir: Path = Path("config")`, `gcp_project: str = "artful-timing-506108-n8"`, `gcp_region: str = "us-central1"`, `db_bucket: str | None = None`, `db_object: str = "health.db"`, `token_secret: str | None = None`, `client_secret_secret: str | None = None`, `journal_sheet_id: str | None = None`, `timezone: str = "Asia/Kolkata"`, `model_default: str`; property `db_path -> Path` (= `data_dir / "health.db"`, or `data_dir / "synthetic.db"` when `data_mode == "synthetic"`); `get_settings() -> Settings` (cached).
- Produces: every former `Path(__file__)...` path in carried modules reads from `get_settings()`.

- [ ] **Step 1:** Create `C:\Users\karth\calibrated-health-agent`, `git init -b main`, set local `user.name` / `user.email` to the Global Constraints identity.
- [ ] **Step 2:** Write `tests/test_settings.py`:
```python
def test_db_path_real(monkeypatch, tmp_path):
    monkeypatch.setenv("CHA_DATA_DIR", str(tmp_path))
    assert Settings().db_path == tmp_path / "health.db"

def test_db_path_synthetic(monkeypatch, tmp_path):
    monkeypatch.setenv("CHA_DATA_DIR", str(tmp_path)); monkeypatch.setenv("CHA_DATA_MODE", "synthetic")
    assert Settings().db_path == tmp_path / "synthetic.db"

def test_rejects_unknown_mode(monkeypatch):
    monkeypatch.setenv("CHA_DATA_MODE", "prod")
    with pytest.raises(ValidationError): Settings()

def test_defaults_pin_project_and_timezone():
    s = Settings(); assert s.gcp_project == "artful-timing-506108-n8" and s.timezone == "Asia/Kolkata"
```
- [ ] **Step 3:** Run `uv run pytest tests/test_settings.py -v` → FAIL (module missing).
- [ ] **Step 4:** Create the workspace (`[tool.uv.workspace] members = ["packages/*", "apps/*"]`), the three packages, `Settings`. Set `model_default` to the exact Gemini 3.5 Flash-Lite model ID as listed on the Gemini API models page (ai.google.dev/gemini-api/docs/models) or returned by `GET https://generativelanguage.googleapis.com/v1beta/models` (verify the string; do not guess). Pin dependencies: `google-adk==2.7.1` for now (upgraded in Task 11), plus the carried-over deps.
- [ ] **Step 5:** Copy carried modules and tests; replace `sys.path.insert(... "scripts")` imports with package imports (`from health_data import client`), and module-level paths with `get_settings()`. `.gitignore` must cover `data/`, `config/*.json`, `config/*.bak*`, `.env`, `.venv/`, caches, `infra/.terraform/`, `*.tfstate*`, `.playwright-mcp/`.
- [ ] **Step 6:** Copy research notes to `docs/research/`; remove the data-audit facts (history start date, wear counts, journal counts, DB size) from `00-synthesis.md` §1 and any other file. Verify: a `git grep` for each scrubbed fact (history start date, wear/journal counts, DB sizes) → no output.
- [ ] **Step 7:** Run `uv run pytest -q` → all carried tests + 4 new pass (expect 53 passed). Run `uv run ruff check .` and `uv run pyright` → clean (add targeted `# pyright: ignore` only on carried code with a TODO naming Phase 2 if needed).
- [ ] **Step 8:** Commit `chore: bootstrap calibrated-health-agent workspace with carried-over harness`. Create the GitHub repo: `gh repo create kb2326/calibrated-health-agent --private --source . --push --description "A personal health agent that keeps score"`.

### Task 2: CI on GitHub Actions

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 1 workspace commands.
- Produces: required check named `ci` (jobs: `lint`, `types`, `test`).

- [ ] **Step 1:** Write `ci.yml`: on `push` to `main` and `pull_request`; `astral-sh/setup-uv` (pinned version), `uv sync --all-packages --frozen`, then `uv run ruff check .`, `uv run pyright`, `uv run pytest -q`. No secrets, no network calls in tests.
- [ ] **Step 2:** Push; run `gh run watch --exit-status` → success.
- [ ] **Step 3:** Commit `ci: lint, types and tests on every push`.

### Task 3: Schema migration and VACUUM

**Files:**
- Modify: `packages/health_data/src/health_data/db.py`
- Test: `tests/test_db_migrate.py`

**Interfaces:**
- Produces: `migrate(conn) -> int` (returns the resulting `PRAGMA user_version`; target **1**); version 1 creates `journal_submissions(id INTEGER PRIMARY KEY, date TEXT NOT NULL, mood INT, energy INT, soreness INT, note TEXT, tags TEXT, submitted_at TEXT NOT NULL, source TEXT NOT NULL, sheet_row INT, row_hash TEXT NOT NULL, imported_at TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('ok','late','edited','invalid')), UNIQUE(row_hash))` with triggers rejecting UPDATE and DELETE; migrates existing `journal` rows into it (`source='cli'`, `status='ok'`); creates view `journal_outcome(date, mood, energy, soreness, submission_id)` = the earliest `ok` submission per date; creates table `devices(id TEXT PRIMARY KEY, display_name TEXT, raw_json TEXT NOT NULL, fetched_at TEXT NOT NULL)`; `vacuum(path: Path) -> tuple[int, int]` (bytes before, after). `init_db()` calls `migrate`.

- [ ] **Step 1:** Tests: `test_migrate_from_v0_moves_journal_rows` (old `journal` rows appear in `journal_submissions` and `journal_outcome`; `user_version == 1`); `test_migrate_is_idempotent`; `test_journal_submissions_reject_update_and_delete`; `test_outcome_is_earliest_ok_submission`; `test_vacuum_shrinks_after_delete` (insert 10k rows, delete, vacuum → after < before).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement with `PRAGMA user_version` and `ALTER TABLE` guarded by column checks.
- [ ] **Step 4:** Run → PASS. Then on the real DB copy: `uv run cha-data db vacuum` (CLI wiring in Task 5's `cli.py`; until then call the function) and record before/after sizes in the commit message only (no values in files).
- [ ] **Step 5:** Commit `feat(data): versioned schema migrations and vacuum`.

### Task 4: Pure and complete ingestion — reconcile, devices, extra scopes and types

**Files:**
- Create: `packages/health_data/src/health_data/reconcile.py`
- Modify: `client.py`, `sync.py`, `config/health.yaml`
- Test: `tests/test_reconcile.py`, `tests/test_sync_types.py`

**Interfaces:**
- Produces: `iter_reconciled(data_type: str, start: date, end: date) -> Iterator[dict]` dispatching `dataPoints.reconcile` through `client._read` (fine-grained, multi-source-merged, excludes non-worn intervals — used for **parity checks and wear inputs only**, never stored point-by-point in SQLite); `daily_summed(data_type, start, end) -> dict[date, float]` from `dailyRollUp` (the stored daily value); `parity_report(data_type, start, end) -> list[tuple[date, float, float]]` (rollup vs summed reconcile per day); `SUMMED_TYPES = frozenset({"steps","distance","total-calories","active-minutes","floors","active-zone-minutes"})`; `client.list_paired_devices()` results upserted into `devices`; `config/health.yaml` `scope_categories` adds `profile` and `settings`.
- Consumes: `db.migrate` (Task 3).

- [ ] **Step 1:** Read the live discovery document (`service()._rootDesc` or the REST reference) for `dataPoints.reconcile` request/response fields; note them in the module docstring.
- [ ] **Step 2:** Tests with a fake service object: `test_reconcile_uses_allowlisted_method` (asserts `_read` called with `"dataPoints.reconcile"`); `test_summed_types_store_daily_rollup_not_points` (sync of `steps` writes one `daily_metrics` row per day and **no** per-minute rows); `test_db_stays_under_50mb_for_200_synthetic_days` (fixture sync of all types × 200 days → file size < 50 MB); `test_unknown_type_records_zero_and_continues` (Review Focus 5: fake raises 400 for one type → sync result marks it `error`, other types still synced, exit status reflects partial failure); `test_scopes_include_profile_and_settings`.
- [ ] **Step 3:** Run → FAIL.
- [ ] **Step 4:** Implement. Raw points kept with their source for point/session types (HRV, SpO2, sleep, exercise); summed types stored as daily rollups. Then live parity check by calling `parity_report` for the last 14 days (the `cha-data parity` command is wired in Task 5) → for each summed type, daily rollup vs summed reconcile agree within 2% on worn days; record disagreements (if any) in `docs/research/data-notes.md` without values, only percentages.
- [ ] **Step 5:** Device probe: `uv run cha-data probe --days 30` lists each readable type with point counts. Add every type with ≥1 point among: `daily-heart-rate-variability`, `daily-oxygen-saturation`, `daily-respiratory-rate`, `respiratory-rate-sleep-summary`, `daily-sleep-temperature-derivations`, `active-zone-minutes`, `time-in-heart-rate-zone`, `daily-vo2-max`, `sedentary-period`, `floors` to `config/health.yaml` with the right `agg`. Add `extract_value` handlers for each added type, with one unit test per handler using a fixture point shaped like the probe output (fixture values synthetic).
- [ ] **Step 6:** Run all tests → PASS. Commit `feat(data): reconciled sync, device inventory, profile/settings scopes, extra data types`.

### Task 5: Full-history backfill and the `cha-data` CLI

**Files:**
- Create: `packages/health_data/src/health_data/backfill.py`, `cli.py`
- Test: `tests/test_backfill.py`

**Interfaces:**
- Produces: `backfill(since: date, types: list[str] | None = None) -> dict[str, int]` (rows inserted per type; resumable — skips windows before each type's cursor); Typer app `cha-data` with commands `sync`, `backfill --since YYYY-MM-DD`, `probe --days N`, `parity --days N`, `db vacuum`, `db migrate`, `db pull`, `db push`, `journal import`, `auth login`, `auth status`, `auth push-secret`; console script registered in `health_data`'s pyproject.
- Consumes: `iter_reconciled` (Task 4), existing `iter_data_points`, `iter_daily_rollups`.

- [ ] **Step 1:** Tests with a fake client: `test_backfill_splits_windows_per_type_cap` (heart-rate windows ≤14 days, others ≤90); `test_backfill_resumes_after_failure` (Review Focus 1: fake raises 429 after retries on window 3 → raises, cursor at end of window 2, rerun inserts only remaining windows, total rows equal a clean run, no duplicates); `test_backfill_is_idempotent` (second run inserts 0).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Real backfill on the owner machine: `uv run cha-data backfill --since <start-date>`, then `uv run cha-data backfill --since <start-date>` again → second run reports 0 new rows for every type.
- [ ] **Step 6:** Commit `feat(data): resumable full-history backfill and cha-data CLI`.

### Task 6: Journal capture via Google Form → Sheet

**Files:**
- Create: `packages/health_data/src/health_data/journal_import.py`
- Test: `tests/test_journal_import.py`

**Interfaces:**
- Produces: `JournalRow` (pydantic: `date: date`, `mood: int`, `energy: int`, `soreness: int` each `1..10`, `note: str | None`, `submitted_at: datetime` tz-aware, `sheet_row: int`); `fetch_rows(sheet_id: str) -> list[list]` (Sheets API `spreadsheets.values.get` with `valueRenderOption=UNFORMATTED_VALUE`, `dateTimeRenderOption=SERIAL_NUMBER`; columns mapped **by position**: timestamp, date, mood, energy, soreness, note, tags (comma-separated → `tags: list[str]` on `JournalRow`, stored as JSON in the `tags` column of `journal_submissions`); scope `spreadsheets.readonly`); `parse_rows(rows: list[list], tz: str) -> tuple[list[JournalRow], list[str]]`; `append_submissions(conn, rows: list[JournalRow]) -> dict[str, int]` (counts by status). Rules: `row_hash = sha256(sheet_row|timestamp|date|mood|energy|soreness|note|tags)`; a known hash is skipped; a known `sheet_row` with a new hash is stored as `edited`; a submission with `submitted_at` later than D+1 06:00 `Asia/Kolkata` for date D is stored as `late`; invalid values stored as `invalid` with the reason (never in outcomes). The outcome for D is the earliest `ok` submission (view from Task 3). Phase 2 adds the lower bound "after D's lock".
- Consumes: `db.migrate` v1 columns.

- [ ] **Step 1:** Owner step (manual, ~5 min): create a Google Form with fields in this order — *Date* (date), *Mood*, *Energy*, *Soreness* (linear scale 1–10), *Note* (paragraph, optional), *Tags* (checkboxes, optional: alcohol · caffeine after 2pm · late meal · high stress · hard training); link responses to a Sheet; set the Sheet's time zone to `Asia/Kolkata` (File → Settings); put the Sheet ID in `.env` as `CHA_JOURNAL_SHEET_ID`. Do not publish the sheet to the web. For local runs: `gcloud auth application-default login --scopes=https://www.googleapis.com/auth/spreadsheets.readonly,https://www.googleapis.com/auth/cloud-platform`.
- [ ] **Step 2:** Tests (Review Focus 3 and 6): `test_resubmission_kept_and_first_ok_is_outcome`; `test_sheet_edit_stored_as_edited_not_outcome`; `test_late_submission_flagged` (submitted D+1 07:00 IST for D → `late`); `test_late_night_within_window_ok` (submitted 00:30 IST on D+1 for D → `ok`, date D); `test_out_of_range_stored_invalid_with_reason`; `test_bad_date_stored_invalid`; `test_reimport_is_noop` (same rows twice → second run all skipped); `test_serial_number_timestamp_parsed_in_ist`; `test_note_stored_verbatim_as_data` (a note containing "ignore previous instructions" is stored unchanged — wrapping happens in the agent layer, Phase 3).
- [ ] **Step 3:** Run → FAIL. **Step 4:** Implement. **Step 5:** Run → PASS.
- [ ] **Step 6:** Live check: submit one Form entry from the phone; `uv run cha-data journal import` → 1 `ok`; rerun → 0 new.
- [ ] **Step 7:** Commit `feat(data): journal import from Google Form responses`.

### Task 7: GCS persistence with a generation precondition

**Files:**
- Create: `packages/health_data/src/health_data/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces: `pull_db(bucket: str, obj: str, dest: Path) -> int | None` (returns object generation, `None` if absent; records it in `data/.db_generation`); `push_db(bucket: str, obj: str, src: Path, if_generation_match: int | None) -> int` (raises `ConcurrentUpdateError` on precondition failure; `if_generation_match=0` when creating); `require_fresh(bucket, obj) -> None` (raises `StaleLocalDbError` if the bucket generation differs from `data/.db_generation`); every writing `cha-data` command calls `require_fresh` when `CHA_DB_BUCKET` is set, then pushes after success.
- Consumes: `google.cloud.storage.Client` (injected for tests).

- [ ] **Step 1:** Tests with a fake storage client: `test_pull_returns_generation`; `test_push_uses_generation_precondition`; `test_concurrent_push_raises` (Review Focus 2: generation changed between pull and push → `ConcurrentUpdateError`, object untouched); `test_first_push_creates_with_zero_precondition`; `test_local_write_refuses_when_stale` (Review Focus 7).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (run `PRAGMA wal_checkpoint(TRUNCATE)` before upload). **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(data): GCS-backed database with optimistic concurrency`.

### Task 8: Tokens in Secret Manager and the sync job entrypoint

**Files:**
- Create: `packages/health_data/src/health_data/secrets.py`, `apps/jobs/pyproject.toml`, `apps/jobs/src/jobs/sync_job.py`, `apps/jobs/Dockerfile`
- Modify: `packages/health_data/src/health_data/auth.py`
- Test: `tests/test_sync_job.py`, `tests/test_auth_secrets.py`

**Interfaces:**
- Produces: `read_secret(project: str, name: str) -> str`, `write_secret(project: str, name: str, value: str) -> None`; `auth.get_credentials()` loads client + token from Secret Manager when `Settings.token_secret` is set, else from `config/`; raises `ReauthRequired("Run `cha-data auth login` then `cha-data auth push-secret`")` on `invalid_grant`; `sync_job.main(argv: list[str] | None = None) -> int` = pull_db → migrate → sync → journal import → push_db; `--dry-run` runs every step against a temp copy and skips the push; exit 0 only if every step succeeded; structured JSON log line per step with `severity=ERROR` on failure (feeds the alert in Task 9); `write_secret` disables and destroys all but the newest version (stay within 6 free active versions).
- Consumes: Tasks 3–7.

- [ ] **Step 1:** Tests: `test_invalid_grant_raises_reauth_required` (Review Focus 4); `test_job_exit_nonzero_on_reauth` (no push happens); `test_job_happy_path_order` (fakes record call order pull→migrate→sync→import→push); `test_job_nonzero_on_concurrent_update`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; Dockerfile: `python:3.13-slim`, uv install from lockfile, non-root user, entrypoint `python -m jobs.sync_job`. **Step 4:** Run → PASS.
- [ ] **Step 5:** `docker build -f apps/jobs/Dockerfile -t sync-job .` (image installs only `uv sync --package jobs --no-dev --frozen`) → success and image size < 300 MB; `docker run --rm -e CHA_DATA_MODE=synthetic sync-job --dry-run` → exits 0.
- [ ] **Step 6:** Commit `feat(jobs): sync job with Secret Manager credentials`.

### Task 9: Terraform — the free-tier GCP slice

**Files:**
- Create: `infra/{versions.tf,backend.tf,variables.tf,services.tf,budget.tf,storage.tf,secrets.tf,registry.tf,iam.tf,job.tf,scheduler.tf,outputs.tf}`, `infra/bootstrap.sh`, `infra/README.md`

**Interfaces:**
- Produces: GCS state bucket `artful-timing-506108-n8-tfstate` (created once by `bootstrap.sh`, versioned); data bucket `artful-timing-506108-n8-health-db` (us-central1, uniform access, public access prevention enforced, versioning on, lifecycle: keep 10 noncurrent versions); secrets `oauth-client`, `oauth-token`; Artifact Registry repo `cha` (Docker, cleanup policy keep 3 most recent); service account `sync-job@…` with `roles/storage.objectAdmin` on the data bucket and `roles/secretmanager.secretAccessor` on the two secrets only; Cloud Run job `sync` (1 task, max retries 1, timeout 15 min, **2Gi**, 1 vCPU, env `CHA_DB_BUCKET`, `CHA_TOKEN_SECRET`, `CHA_CLIENT_SECRET_SECRET`, `CHA_JOURNAL_SHEET_ID`); Cloud Scheduler job `sync-hourly` `0 5-12 * * *` + `sync-evening` `30 22 * * *`, time zone `Asia/Kolkata`, calling the Cloud Run Admin API `…/jobs/sync:run` with an **`oauth_token`** (not OIDC) for an invoker SA holding `roles/run.invoker` on the job (Cloud Scheduler's 3 free jobs are per billing account — this phase uses 2); billing budget "calibrated-health-agent" amount 5 USD, thresholds 0.4 and 0.8, email to owner (provider needs `user_project_override = true` and `billing_project = "artful-timing-506108-n8"`; the applying identity needs Billing Account Costs Manager on `01DA8F-C0DAA3-A37763`); email notification channel + log-based alert policy firing on any `sync` job execution failure or `severity>=ERROR` log line from the job.
- Services enabled: run, cloudscheduler, secretmanager, artifactregistry, billingbudgets, sheets, iam, monitoring. **Not** cloudbuild.

- [ ] **Step 1:** `terraform fmt -check` and `terraform validate` → success.
- [ ] **Step 2:** `terraform plan -out tfplan` → shows only the resources above (review the plan output line by line; no load balancer, no always-on service, no VPC).
- [ ] **Step 3: Gate — owner approval.** Show the plan summary and the cost table (§12a of the architecture). Proceed only on the owner's explicit yes.
- [ ] **Step 4:** `terraform apply tfplan` → success. Build locally and push: `gcloud auth configure-docker us-central1-docker.pkg.dev` then `docker push us-central1-docker.pkg.dev/artful-timing-506108-n8/cha/sync-job:<git-sha>`; set the job image via a Terraform variable. Trigger a deliberate failure (`--dry-run` with a bad secret name) once and confirm the alert email arrives.
- [ ] **Step 5:** Commit `infra: free-tier GCP slice for the daily sync`.

### Task 10: OAuth in production, secrets loaded, first cloud run

**Files:**
- Modify: `infra/README.md` (runbook)

- [ ] **Step 1: Owner step:** Cloud Console → APIs & Services → OAuth consent screen (project `artful-timing-506108-n8`) → add scopes `googlehealth.profile.readonly`, `googlehealth.settings.readonly` → **Publish app** (In Production). Unverified-app warning at consent is expected.
- [ ] **Step 2:** `uv run cha-data auth login` (owner completes consent) → `uv run cha-data auth status` lists 5 read-only scopes.
- [ ] **Step 3:** `uv run cha-data auth push-secret` uploads client + token to Secret Manager; upload the local DB once with `uv run cha-data db push` (creates with generation precondition 0). From now on GCS is the source of truth; local work starts with `cha-data db pull`.
- [ ] **Step 4:** Share the journal Sheet with `sync-job@artful-timing-506108-n8.iam.gserviceaccount.com` (Viewer).
- [ ] **Step 5:** `gcloud run jobs execute sync --region us-central1 --wait --project artful-timing-506108-n8` → succeeded; the bucket object's generation increased; logs show each step ok.
- [ ] **Step 6:** Next morning: confirm scheduled executions succeeded (`gcloud run jobs executions list --job sync --region us-central1`), and the billing report shows ≈ $0.
- [ ] **Step 7:** Commit `docs(infra): runbook for OAuth, secrets and first cloud run`.

### Task 11: ADK 2.12 and explicit delegation modes

**Files:**
- Modify: `packages/health_agents/pyproject.toml`, `packages/health_agents/src/health_agents/agent.py`
- Test: `tests/test_agent_topology.py`

**Interfaces:**
- Produces: `google-adk==2.12.0` pinned; `root_agent` whose sub-agents set mode explicitly (`single_turn` for all three in Phase 1 — `task` mode is unavailable inside graph workflows per the fact-check, so the final modes are decided with the Phase 3 workflow design); model IDs from `Settings.model_default`. Not on the Phase 1 critical path.

- [ ] **Step 1:** Confirm the exact mode parameter name and values in adk.dev for 2.12.0 (`mode=` on `LlmAgent`); note the doc URL in a comment.
- [ ] **Step 2:** Test: `test_sub_agent_modes_are_explicit` (asserts each sub-agent's mode is set and equals `single_turn`); `test_agents_use_configured_model` (monkeypatch `CHA_MODEL_DEFAULT` → every agent's model equals it). Run → FAIL.
- [ ] **Step 3:** Upgrade and implement; `uv lock`. **Step 4:** Run full suite → PASS (fix carried tests only for API renames, documenting each).
- [ ] **Step 5:** Commit `feat(agents): ADK 2.12 with explicit delegation modes`.

### Task 12: Phase exit — fresh-clone check and docs

**Files:**
- Modify: `README.md` (status table, Phase 1 → done), `docs/architecture.md` (only if reality differed)

- [ ] **Step 1:** Clone into a temp directory; follow the README "Develop" section exactly; `uv run pytest -q` → all pass with no real data present.
- [ ] **Step 2:** Update the README status and the roadmap diagram (Phase 1 done).
- [ ] **Step 3:** Commit `docs: phase 1 complete`; push; CI green.

---

## Exit criteria (from the spec)

The owner journals from a phone (Task 6) · the cloud sync runs daily without the laptop, and failures email the owner (Tasks 9–10) · a fresh clone runs tests green (Task 12) · spend stays ≈ $0 (Task 10 Step 6).

## Next plans

Phase 2 (honest statistics + forecast ledger) gets its own plan once Phase 1 is merged; it consumes `Settings`, `db.migrate`, the GCS store and the job pattern from this plan.
