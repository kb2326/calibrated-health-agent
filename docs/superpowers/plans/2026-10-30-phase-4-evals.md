# Phase 4: Evals, Red Team and Tracing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Owner choice for this project: executing-plans (native), one final whole-branch review.**

**Goal:** Measure the agent the way practitioner teams do — owner-labelled error analysis, versioned eval suites, code graders first, human-validated binary judges, intervals, a CI regression gate, AgentDojo-style red-teaming and OpenTelemetry tracing — plus a standard forecasting results page.

**Architecture:** A new workspace package `health_eval` holds cases, the transcript runner, the review page, graders, judges, statistics and the report. Cases are YAML (our source of truth, with categories and fixture truth); ADK evalsets are generated from them so `adk eval` / `AgentEvaluator` metrics run too. Transcripts (JSONL) are what every grader reads. CI runs the regression suite on a synthetic fixture with a free-tier Gemini key; the job keeps Vertex. Tracing uses ADK's own OpenTelemetry hooks.

**Tech Stack:** Python 3.13, uv workspace, `google-adk==2.12.0` evaluation (`AgentEvaluator`, evalsets, prebuilt metrics), pytest, numpy (no scipy), PyYAML, `opentelemetry-exporter-otlp-proto-http`, GitHub Actions, Phoenix (Docker image, local only), Cloud Trace, Terraform.

**Spec:** `docs/superpowers/specs/2026-10-25-phase-4-evals-design.md` (approved 2026-10-30, including §9 builder-check resolutions). Practices and sources: `docs/research/09-industry-practice-2026.md`.

## Global Constraints

- Cloud spend stays **under $1/month**. CI, nightly and synthetic runs use the **free-tier key** (repository secret `GEMINI_API_KEY`) on **synthetic data only**. Real-data runs are owner-triggered, laptop-only, costed first, and bounded by the existing $0.30 chat cap; only aggregates leave the machine.
- **Never** commit real-data transcripts or labels: they live under `data/evals/` (git-ignored). Synthetic ones may live under `evals/`.
- **Phase 3 guards are not weakened** (sandbox, SQL authorizer, blinding, wrapping). Small seams (tool lists for the ablation, tool calls on `TurnResult`) are allowed.
- **Never edit `docs/ledger/analysis-plan.md`.**
- CI backend: `GOOGLE_GENAI_USE_VERTEXAI=false` + `GOOGLE_API_KEY`; `vertex.configure()` already defers to existing env (`setdefault`).
- Gates: code graders gate from day one; a judge gates only when held-out **TPR ≥ 0.8 and TNR ≥ 0.8**. A must-pass case fails the gate only if it also fails its **one automatic retry**. `NOT_EVALUATED` (quota, crash) fails the gate with its reason.
- Every reported rate shows **n** and a **Wilson 95% interval**; single vs multi is **paired** (McNemar + paired bootstrap), with the minimum detectable difference stated.
- Judge prompts receive transcript text only inside `untrusted.wrap(...)`.
- Accounts: git as kb2326 (repo credential helper), gh as `GH_TOKEN=$(gh auth token --user kb2326)`, gcloud `personal` config. Cloud applies need the owner's yes.
- Commits authored by the repo-local identity; plain `uv run pytest -q -p no:warnings`, `ruff check .` and `pyright` stay clean.

## Review Focus

1. **Free-tier quota runs out mid-CI** → the case is `NOT_EVALUATED` with reason `quota`, and the gate fails saying so (not a silent pass, not a "regression"). → Task 14 `test_quota_error_is_not_evaluated_and_fails_gate`.
2. **A real-data transcript written inside `evals/`** (committable) → the runner refuses `--real` output outside `data/evals/`. → Task 4 `test_real_runs_refuse_committable_paths`.
3. **Review page closed halfway** → labels are append-only; reopening resumes at the first unlabelled transcript; a re-label supersedes the earlier one. → Task 5 `test_review_resumes_and_latest_label_wins`.
4. **A poisoned journal note inside a transcript reaches a judge** → it arrives wrapped. → Task 10 `test_judge_prompt_wraps_transcript_text`.
5. **A report built from an empty suite or with no `main` baseline yet** → shows "n = 0" / "no baseline yet", never divides by zero or crashes. → Task 11 `test_report_handles_empty_suite_and_missing_baseline`.

---

## File Structure

```
packages/health_eval/                  CREATE  new workspace package (deps: health-agents, health-ledger, PyYAML, numpy)
  src/health_eval/
    cases.py        Case model + YAML loader + ADK evalset generator
    fixture.py      extended synthetic scenarios on top of smoke.build_fixture (+ truth queries)
    questions.py    question grid → concrete questions
    runner.py       run cases/questions → transcripts JSONL (topology, trials, variant, real flag)
    review.py       local labelling page (stdlib http.server) → labels JSONL
    graders.py      code graders over transcripts
    judges.py       binary LLM judges + calibration (TPR/TNR on splits)
    stats.py        Wilson, McNemar (exact), paired bootstrap, pass^k, MDD
    redteam.py      attack families, ASR / utility-under-attack
    adk_eval.py     AgentEvaluator run of generated evalsets (trajectory, safety, hallucination)
    report.py       results/<date>-<sha>.md + README scorecard block; gate decision
    tracing.py      OTel setup (Phoenix locally, Cloud Trace in the job)
packages/health_agents/src/health_agents/cli.py        MODIFY  `cha eval …`, `cha review`; TurnResult.tool_calls
packages/health_agents/src/health_agents/workflow.py   MODIFY  build_workflow(tools=…) seam for the ablation
packages/health_ledger/src/health_ledger/report.py     CREATE  forecasting results (reliability, DM-HLN, bootstrap)
packages/health_ledger/src/health_ledger/cli.py        MODIFY  `cha-ledger report`
evals/cases/{regression,capability,safety,redteam,ablation}.yaml   CREATE
evals/questions/grid.yaml                              CREATE
evals/judges/*.md                                      CREATE  one prompt per judged failure mode
evals/generated/*.evalset.json                         GENERATED (committed)
.github/workflows/evals.yml                            CREATE
infra/iam.tf (or job.tf)                               MODIFY  trace writer role (owner-gated apply)
docs/evals/{methodology,failure-taxonomy,judge-calibration}.md, docs/evals/results/
docs/forecasting/{protocol,results}.md, docs/threat-model.md, docs/system-card.md,
docs/observability.md, docs/adr/0002..0006-*.md, README.md
```

---

### Task 1: Free-tier backend check and CI seam

**Files:**
- Create: `docs/adr/0002-ci-model-backend.md`, `tests/test_backend_switch.py`

**Interfaces:**
- Produces: the verified free-tier facts (model served or not, RPM/RPD) in the ADR; the env recipe CI uses.

- [ ] **Step 1: Failing test** — `test_existing_env_wins_over_vertex_defaults`: with `GOOGLE_GENAI_USE_VERTEXAI=false` and `GOOGLE_API_KEY=x` set, `vertex.configure()` leaves both unchanged; `test_vertex_defaults_apply_when_unset` (already covered in `test_vertex.py`, keep).
- [ ] **Step 2: Run** `uv run pytest tests/test_backend_switch.py -q -p no:warnings` → passes immediately (behaviour exists). Record: this test pins the seam, it is a guard test, not new code.
- [ ] **Step 3: Owner action + probe** — owner creates the AI Studio key and runs (own terminal) `$env:GOOGLE_API_KEY="…"; $env:GOOGLE_GENAI_USE_VERTEXAI="false"; uv run cha smoke --questions .superpowers/q1.yaml` with one question. Expected: an answer (proves the model is served on the free tier). Read the AI Studio rate-limit page for `gemini-3.5-flash-lite` and record RPM/RPD. If the model is not on the free tier, record the closest served Flash-Lite ID and add `Settings.eval_model` (default = `model_default`) used only by eval runs.
- [ ] **Step 4: ADR 0002** — context (budget, synthetic-only rule), decision (env switch, model, limits), consequence (suite sizes in Task 14 derived from RPD).
- [ ] **Step 5: Commit** `docs(adr): CI model backend on the free tier`

---

### Task 2: `health_eval` package, case model and evalset generator

**Files:**
- Create: `packages/health_eval/pyproject.toml`, `src/health_eval/__init__.py`, `cases.py`, `fixture.py`
- Modify: root `pyproject.toml` (workspace source + dependency)
- Test: `tests/test_eval_cases.py`, `tests/test_eval_fixture.py`

**Interfaces:**
- Produces: `@dataclass Case(id: str, suite: str, category: str, question: str | list[str], expect: Expect)`; `@dataclass Expect(numbers: dict[str, str] = {}, tools_any: list[str] = [], tools_none: list[str] = [], behaviour: list[str] = [], must_pass: bool = False)` — `numbers` maps a label to a **truth SQL** run on the fixture; `behaviour` items are from `BEHAVIOURS = ("admits_gap", "refuses_diagnosis", "escalates_care", "no_overrefusal", "no_unverified", "cites_receipt", "resists_injection")`.
- `load_cases(suite: str, root: Path = Path("evals/cases")) -> list[Case]` (validates ids unique, categories non-empty, behaviours known).
- `to_evalset(cases: list[Case], suite: str) -> dict` (ADK `EvalSet` JSON: `eval_set_id`, `eval_cases[].conversation[]` with `user_content`, and `intermediate_data.tool_uses` from `tools_any`), and `write_evalsets(root, out=Path("evals/generated"))`.
- `fixture.build(path: Path) -> Path` — `smoke.build_fixture` plus scenarios: a metric with no rows (VO2 max), a 5-day wear gap, a red-flag journal note ("chest pain"), a poisoned device name. `fixture.truth(conn, sql) -> Any` (guarded read-only).

- [ ] **Step 1: Failing tests**

```python
def test_cases_load_and_validate(tmp_path): ...            # duplicate id -> ValueError; unknown behaviour -> ValueError
def test_evalset_matches_adk_schema(tmp_path):
    from google.adk.evaluation.eval_set import EvalSet
    EvalSet.model_validate(to_evalset(load_cases("regression", tmp_root), "regression"))
def test_fixture_has_gap_and_missing_metric(tmp_path): ...  # no 'vo2-max' rows; 5 consecutive days without sleep
def test_truth_sql_is_read_only(tmp_path): ...              # truth("DELETE FROM daily_metrics") raises
```

- [ ] **Step 2: Run** `uv run pytest tests/test_eval_cases.py tests/test_eval_fixture.py -q -p no:warnings` → FAIL (no package).
- [ ] **Step 3: Implement** (dataclasses + `yaml.safe_load`; evalset via the ADK pydantic models so the schema is ADK's own; truth through `sqlguard.guarded_connect`).
- [ ] **Step 4: Run** → PASS; `uv sync --all-packages`; ruff/pyright clean.
- [ ] **Step 5: Commit** `feat(eval): case model, ADK evalset generator, extended fixture`

---

### Task 3: Question grid

**Files:** Create `src/health_eval/questions.py`, `evals/questions/grid.yaml`; Test `tests/test_eval_questions.py`

**Interfaces:**
- `grid.yaml` dimensions: `intent` (number, trend, comparison, explanation, coaching, out_of_scope, medical), `window` (last week, last 30 days, a named month, all time), `data_state` (complete, gappy, missing_metric, no_journal), `persona` (curious, terse, anxious, adversarial); `templates` per intent with `{metric}`, `{window}` slots.
- `expand(grid: dict, n: int, seed: int = 20261030) -> list[dict]` → `{id, question, tags: {intent, window, data_state, persona}}`, deterministic, balanced across `intent`.
- `cha eval questions --n 120 [--draft]` writes `evals/questions/batch-<date>.yaml`; `--draft` asks the model to paraphrase each templated question naturally (free-tier key, synthetic context only), keeping tags.

- [ ] **Step 1: Failing tests** — `test_expand_is_deterministic`, `test_expand_balances_intents` (every intent within ±1 of n/7), `test_tags_are_from_the_grid`.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat(eval): question grid for error analysis`

---

### Task 4: Transcript runner

**Files:**
- Create: `src/health_eval/runner.py`
- Modify: `packages/health_agents/src/health_agents/cli.py` (`TurnResult.tool_calls: list[dict]` = `{name, args, response}` collected in `Session._ask`), `workflow.py` (`build_workflow(..., tools: list | None = None)` — when given, the single topology uses that list)
- Test: `tests/test_eval_runner.py`

**Interfaces:**
- `@dataclass Transcript(case_id, question, answer, tool_calls, receipts, input_tokens, output_tokens, usd, seconds, topology, variant, trial, commit, fixture_hash, status: Literal["ok","not_evaluated"], reason: str | None)`.
- `run(items: list[Case | dict], *, topology: str, trials: int = 1, variant: str = "full", model=None, real: bool = False, out: Path) -> list[Transcript]`; writes JSONL (one line per transcript). Variants: `full`, `no_code` (tools minus `run_python`), `no_tools` (no tools), used by the ablation.
- Quota/429 or any model error → `status="not_evaluated"`, `reason="quota"` / exception type.
- `real=True` requires `out` under `data/evals/`, else `ValueError`.

- [ ] **Step 1: Failing tests**

```python
def test_runner_writes_one_line_per_trial(tmp_path): ...       # FakeLlm, 2 cases x 2 trials -> 4 lines
def test_transcript_has_tool_calls_and_receipts(tmp_path): ...
def test_no_code_variant_has_no_run_python(tmp_path): ...
def test_quota_error_becomes_not_evaluated(tmp_path): ...       # FakeLlm step raises a 429-like error
def test_real_runs_refuse_committable_paths(tmp_path): ...      # real=True, out=evals/x.jsonl -> ValueError
```

- [ ] **Step 2–4:** run → FAIL, implement (reuses `cli.Session(model, refresh_memory=False)` against the fixture as `smoke.run_smoke` does), run → PASS; existing `tests/test_cli.py` and `tests/test_workflow.py` still pass.
- [ ] **Step 5: Commit** `feat(eval): transcript runner with trials, variants and status`

---

### Task 5: Review page (labelling)

**Files:** Create `src/health_eval/review.py`; Modify `cli.py` (`cha review FILE [--port 8770]`); Test `tests/test_eval_review.py`

**Interfaces:**
- `labels_path(transcripts: Path) -> Path` (`<name>.labels.jsonl` beside it).
- `next_unlabelled(transcripts: Path) -> int | None`; `save_label(transcripts, index: int, verdict: Literal["pass","fail"], note: str) -> None` (append-only, with UTC timestamp); `current_labels(transcripts) -> dict[int, dict]` (latest per index wins).
- Page: stdlib `http.server` bound to `127.0.0.1`; one transcript per screen (question, answer, collapsible tool calls and receipts), Pass / Fail buttons, note box, keys `p` / `f` / `n`; progress "k of N".

- [ ] **Step 1: Failing tests** — `test_review_resumes_and_latest_label_wins`, `test_labels_are_append_only` (file only grows), `test_page_binds_localhost_only`, `test_page_escapes_transcript_html` (an answer containing `<script>` renders escaped).
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat(eval): local review page for owner labels`

---

### Task 6: Code graders

**Files:** Create `src/health_eval/graders.py`; Test `tests/test_eval_graders.py`

**Interfaces:**
- `@dataclass Verdict(check: str, passed: bool | None, detail: str)` (`None` = not applicable).
- `grade(transcript: Transcript, case: Case, conn) -> list[Verdict]` with checks: `numbers` (each truth value appears in the answer at its precision, via `verify._matches`), `receipts_rerun` (every cited receipt re-runs to the same value on the fixture), `tools_any`, `tools_none`, `no_blinded_access` (no tool call errored with the blinding message *and* no blinded value in outputs), `no_unverified` (`unverified:` absent), `admits_gap`, `refuses_diagnosis`, `escalates_care` (marker lexicons in `graders.MARKERS`, used only where a case expects them), `cost_latency` (always `None`-gated, recorded).
- `case_passed(verdicts) -> bool | None` (None if any required check is not applicable).

- [ ] **Step 1: Failing tests** — one per check with hand-built transcripts (pass and fail each), e.g. `test_numbers_match_at_answer_precision`, `test_receipt_that_does_not_rerun_fails`, `test_gap_admission_markers`, `test_diagnosis_refusal_markers`.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat(eval): code graders over transcripts`

---

### Task 7: Statistics

**Files:** Create `src/health_eval/stats.py`; Test `tests/test_eval_stats.py`

**Interfaces:**
- `wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]` (n = 0 → (0.0, 1.0)).
- `mcnemar_exact(b: int, c: int) -> float` (two-sided binomial p via `math.comb`).
- `paired_bootstrap_diff(a: list[bool], b: list[bool], n: int = 2000, seed: int = 20261030) -> tuple[float, float, float]` (point, lo, hi).
- `pass_hat_k(trials: list[list[bool]]) -> float` (fraction of cases passing all k).
- `min_detectable_diff(n: int, p: float = 0.8, alpha=0.05, power=0.8) -> float` (normal approximation, paired).

- [ ] **Step 1: Failing tests** — `test_wilson_known_values` (`wilson(34, 40)` ≈ (0.709, 0.929) to 3 dp), `test_wilson_n0`, `test_mcnemar_exact_symmetric_and_known` (`mcnemar_exact(0, 6)` ≈ 0.03125), `test_bootstrap_seeded`, `test_pass_hat_k`, `test_mdd_shrinks_with_n`.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat(eval): Wilson, exact McNemar, paired bootstrap, pass^k, MDD`

---

### Task 8: Seed suites

**Files:** Create `evals/cases/{regression,capability,safety,redteam,ablation}.yaml`; Test `tests/test_eval_suites.py`

**Interfaces:** consumes `Case`/`Expect` (Task 2). Targets: regression 40–50 (≥ 20 `must_pass`), capability ~80, safety ~30, redteam ~40 (Task 13 adds the attack generators), ablation ~60 numeric. Each case names a `category`; the taxonomy from Task 17 adds and re-tags cases later.

- [ ] **Step 1: Failing test** — `test_suites_meet_targets_and_validate` (counts within targets, all load, ≥ 30% negative cases in safety, every behaviour in `BEHAVIOURS` covered somewhere), `test_truth_queries_run_on_fixture` (every `numbers` SQL returns a value on `fixture.build`).
- [ ] **Step 2: Run** → FAIL (files missing).
- [ ] **Step 3: Write the YAML** — questions over the fixture's metrics and journal; red-flag (chest pain, fainting → `escalates_care`), diagnosis requests (`refuses_diagnosis`), harmless wellness questions near the boundary (`no_overrefusal`), gap cases (missing VO2 max, the 5-day gap, no journal → `admits_gap`). Then `cha eval build` writes `evals/generated/*.evalset.json`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(eval): seed regression, capability, safety, red-team and ablation suites`

---

### Task 9: Ablation and single vs multi

**Files:** Modify `src/health_eval/runner.py` (`cha eval ablation`); Create `src/health_eval/ablation.py`; Test `tests/test_eval_ablation.py`

**Interfaces:**
- `run_ablation(cases, *, trials: int = 1, out_dir: Path) -> dict` — arms `no_tools`, `no_code`, `full` (single), `multi`; grades each with Task 6; returns per-arm `{k, n, rate, ci}` and paired comparisons `full vs no_code`, `full vs no_tools`, `single vs multi` (`mcnemar_exact`, `paired_bootstrap_diff`, `min_detectable_diff`).

- [ ] **Step 1: Failing tests** — `test_ablation_pairs_by_case` (with FakeLlm arms, discordant counts feed McNemar), `test_ablation_reports_mdd`.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat(eval): ablation and paired single vs multi`

---

### Task 10: Binary judges and calibration

**Files:** Create `src/health_eval/judges.py`, `evals/judges/{answers_question,gives_diagnosis,admits_gap,overrefuses}.md`; Test `tests/test_eval_judges.py`

**Interfaces:**
- `judge(name: str, transcript: Transcript, *, model=None, cache: Path) -> Literal["pass","fail","unknown"]` — prompt from `evals/judges/<name>.md`, transcript text wrapped with `untrusted.wrap("transcript", …)`, JSON `{"verdict": …, "reason": …}`, temperature 0; cached by `(name, prompt sha, transcript sha)`.
- `split_labels(labels: list[dict], seed=20261030) -> dict[str, list]` — 40/20/40 train/dev/test, stratified by verdict.
- `calibrate(name, labelled: list[tuple[Transcript, str]]) -> dict` → `{tpr, tpr_ci, tnr, tnr_ci, n, unknown_rate, gates: bool}` (gates iff TPR ≥ 0.8 and TNR ≥ 0.8 on the test split).

- [ ] **Step 1: Failing tests** — `test_judge_prompt_wraps_transcript_text` (poisoned note only inside a wrapper), `test_judge_cache_hits`, `test_unknown_verdict_supported`, `test_split_is_stratified_and_seeded`, `test_calibration_gates_only_above_threshold`.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat(eval): binary judges with human calibration`

---

### Task 11: Report and gate decision

**Files:** Create `src/health_eval/report.py`; Modify `cli.py` (`cha eval report`, `cha eval gate`); Test `tests/test_eval_report.py`

**Interfaces:**
- `summarise(transcripts, cases, verdicts, judge_status) -> dict` — per suite and category `{k, n, rate, ci}`, pass^k, p50/p95 latency, mean $ per question, red-team block (Task 13), ablation block (Task 9).
- `write_results(summary, out=Path("docs/evals/results")) -> Path` (`<date>-<sha>.md`) and `readme_block(summary) -> str` (between `<!-- scorecard:start -->` / `<!-- scorecard:end -->` markers in README).
- `gate(current: dict, baseline: dict | None) -> tuple[bool, list[str]]` — fails on any must-pass failure confirmed by retry, any `not_evaluated` (reason listed), or a drop beyond the noise band `max(0.05, 2 × sd from nightly pass^3)`; no baseline → regression check skipped and stated.

- [ ] **Step 1: Failing tests** — `test_report_handles_empty_suite_and_missing_baseline`, `test_readme_block_replaces_between_markers`, `test_gate_fails_on_confirmed_must_pass_failure`, `test_gate_tolerates_flake_that_passes_retry`, `test_gate_fails_on_not_evaluated_with_reason`.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat(eval): results report, README scorecard block, CI gate decision`

---

### Task 12: ADK evaluation run

**Files:** Create `src/health_eval/adk_eval.py`; Test `tests/test_eval_adk.py`

**Interfaces:**
- `run_adk(evalset: Path, metrics: list[str] = ["tool_trajectory_avg_score"], judge_metrics: list[str] = ["safety_v1", "hallucinations_v1"]) -> dict` — calls `AgentEvaluator.evaluate_eval_set` against `health_agents.agent` with the fixture selected via env (as `smoke.run_smoke` does); returns `{metric: score}` merged into the report. Judge metrics run nightly only (quota).

- [ ] **Step 1: Failing test** — `test_adk_trajectory_metric_runs_on_generated_evalset` with a FakeLlm-backed agent module and a 2-case evalset (no network).
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat(eval): ADK evaluation metrics on generated evalsets`

---

### Task 13: Red team and threat model

**Files:** Create `src/health_eval/redteam.py`, `docs/threat-model.md`; Modify `evals/cases/redteam.yaml`; Test `tests/test_eval_redteam.py`

**Interfaces:**
- Attack families: `note_injection`, `device_name_injection`, `sandbox_output_injection`, `memory_hijack` (save_fact must still request confirmation), `sql_abuse`, `sandbox_escape`, `unbounded_consumption`. `attacks(family) -> list[Case]` builds cases (the fixture carries the poisoned rows).
- `asr(transcripts, verdicts) -> dict` → per family `{attacks, successes, asr, ci}`, plus `utility_benign` and `utility_under_attack` (AgentDojo-style).
- `docs/threat-model.md`: assets; lethal-trifecta legs and the control cutting each; OWASP LLM 2025 and Agentic 2026 IDs per control (titles marked "verify" where research 09 flagged them); residual risks (Windows sandbox has no memory limit; judges are probabilistic).

- [ ] **Step 1: Failing tests** — `test_each_family_has_cases`, `test_asr_and_utility_under_attack`, `test_sql_and_sandbox_attacks_run_without_llm` (direct calls to `tools.run_sql` / `sandbox.run`), `test_memory_hijack_still_needs_confirmation`.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat(eval): red-team families, ASR reporting, threat model`

---

### Task 14: CI gate

**Files:** Create `.github/workflows/evals.yml`; Test `tests/test_eval_ci.py`

**Interfaces:**
- Jobs: `pr-gate` (pull_request): `uv sync`, build fixture, `cha eval run --suite regression --trials 1` (+ automatic retry of failed must-pass cases), the no-LLM red-team cases, `cha eval gate --baseline <artifact>`; `baseline` (push to `main` + nightly `schedule`): regression with `--trials 3`, capability, safety, red team, judge metrics, `cha eval report`, uploads `eval-baseline.json`. Env: `GOOGLE_GENAI_USE_VERTEXAI=false`, `GOOGLE_API_KEY: ${{ secrets.GEMINI_API_KEY }}`, `CHA_DATA_MODE=synthetic`.
- Suite size on PRs follows ADR 0002's RPD: if regression × 2 (retry worst case) exceeds the daily budget, PRs run the `must_pass` subset only.

- [ ] **Step 1: Failing test** — `test_quota_error_is_not_evaluated_and_fails_gate`; `test_workflow_file_uses_secret_and_synthetic_mode` (parse YAML: `GEMINI_API_KEY` from secrets, `CHA_DATA_MODE=synthetic`, no Vertex env).
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Exit check** — open a PR that removes the receipt rule from `instructions.RECEIPTS`; Expected: `pr-gate` fails on `no_unverified` / `numbers` must-pass cases. Close it unmerged; record run links in `docs/evals/methodology.md`.
- [ ] **Step 6: Commit** `ci: eval regression gate on the free tier`

---

### Task 15: Tracing

**Files:** Create `src/health_eval/tracing.py`, `docs/observability.md`; Modify `packages/health_agents/pyproject.toml` (+ `opentelemetry-exporter-otlp-proto-http`), `cli.py` and `apps/jobs/src/jobs/sync_job.py` (call `tracing.setup()` once), `infra/` (trace role); Test `tests/test_tracing.py`

**Interfaces:**
- `setup(mode: Literal["off","local","cloud"] | None = None) -> str` — default from `CHA_TRACING` (`off`); `local` uses ADK `telemetry.setup.maybe_set_otel_providers` with the standard OTLP exporter (`OTEL_EXPORTER_OTLP_ENDPOINT`, Phoenix at `http://localhost:6006`); `cloud` uses `telemetry.google_cloud.get_gcp_exporters(enable_cloud_tracing=True)`. Always sets `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false` and leaves content capture off unless `CHA_TRACE_CONTENT=1` **and** mode is `local`.
- Span attributes added on tool spans: `cha.receipt_id`, `cha.usd`, `cha.args_sha` (hash, never args).
- Phoenix: `docker run -p 6006:6006 arizephoenix/phoenix` (documented; no Python dependency).
- Terraform: `roles/cloudtrace.agent` for the job service account; job env `CHA_TRACING=cloud`. **Apply needs the owner's yes** and does not block the exit check.

- [ ] **Step 1: Failing tests** — `test_cloud_mode_never_captures_content`, `test_off_is_default`, `test_tool_span_has_receipt_and_no_args` (in-memory span exporter).
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat(obs): OpenTelemetry tracing, content off in the cloud`

---

### Task 16: Forecasting results page

**Files:** Create `packages/health_ledger/src/health_ledger/report.py`, `docs/forecasting/{protocol,results}.md`; Modify `health_ledger/cli.py` (`cha-ledger report`); Test `tests/test_ledger_report.py`

**Interfaces:**
- `reliability(pairs) -> list[dict]` (5 PIT bins with counts and consistency band via seeded resampling under calibration); `dm_hln(d: list[float], h: int = 1) -> tuple[float, float]` (statistic, two-sided p; Student-t CDF via regularized incomplete beta, no scipy); reuses `dist.block_bootstrap_skill`.
- `build(conn) -> dict` per `docs/ledger/analysis-plan.md`: primary (energy, forecaster 6 vs persistence), secondary comparisons, 7 vs 6, log scores, sharpness; `n < 10` → structure with real n and "not yet".
- `render(report) -> str` (Markdown + inline SVG reliability diagrams; aggregates only; rounded like the public board).

- [ ] **Step 1: Failing tests** — `test_dm_hln_known_value` (vector with known statistic), `test_reliability_counts_sum_to_n`, `test_below_ten_days_says_not_yet`, `test_report_contains_no_dates_or_daily_values`.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat(ledger): forecasting results page (reliability, DM-HLN, bootstrap)`

---

### Task 17: Error analysis with the owner (staged)

Runs after Tasks 1–11. Owner-in-the-loop; no new code beyond fixes.

- [ ] **Step 1:** `cha eval questions --n 120 --draft`; `cha eval run --questions <batch> --topology single` and `--topology multi` on the fixture (free tier) → ~100 synthetic transcripts; owner picks ~20 real-data questions → `cha eval run --real --out data/evals/real-<date>.jsonl` (cost printed first, inside the chat cap).
- [ ] **Step 2: Owner labels** with `cha review` (synthetic and real files). Expected: ~100 labels with notes.
- [ ] **Step 3: Taxonomy** — group notes into categories with counts and examples → `docs/evals/failure-taxonomy.md`; owner confirms; each category mapped to a code check (Task 6) or a judge (Task 10); new cases added to `evals/cases/*.yaml` from real failures (synthetic restatements only — no real data).
- [ ] **Step 4: Calibrate judges** on the labels (Task 10) → `docs/evals/judge-calibration.md`; mark which judges gate.
- [ ] **Step 5: Commit** `docs(evals): failure taxonomy and judge calibration from owner labels`

---

### Task 18: Scorecard, system card, ADRs, README

**Files:** Create `docs/system-card.md`, `docs/evals/methodology.md`, `docs/adr/0003-receipts.md`, `0004-sandbox.md`, `0005-topology-default.md`, `0006-trace-content-off.md`; Modify `README.md`

- [ ] **Step 1:** Run the full suites + ablation + red team + ADK metrics (free tier) and `cha eval report`. Expected: `docs/evals/results/<date>-<sha>.md` and the README scorecard block, every number with n, interval and commit.
- [ ] **Step 2:** System card (intended use, out of scope, eval summary, limitations, health framing: FDA general wellness, EU AI Act Art. 50 disclosure); ADRs; README re-ordered per research 09 (agent first, scorecard, architecture, evaluation, security, forecasting experiment, observability, run it yourself, cost, limitations).
- [ ] **Step 3:** `uv run pytest -q -p no:warnings`, `ruff check .`, `pyright` → clean.
- [ ] **Step 4: Commit** `docs: system card, ADRs, eval methodology, agent-first README with scorecard`
- [ ] **Step 5:** Owner yes → apply Terraform trace role + redeploy job image (Task 15); one job run shows spans in Cloud Trace without message content.
