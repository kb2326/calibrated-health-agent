# Phase 5 Web Front End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A web page where the owner talks to the same ADK agent as `cha ask`, watches it work, and opens a re-runnable receipt behind every number. It has a sporty, publishable look, runs on the laptop first, then on Cloud Run behind IAP.

**Architecture:** One FastAPI app (`packages/health_web`) wraps the existing `build_workflow()` with `ag-ui-adk` and filters the AG-UI event stream so no raw rows reach the browser. It adds receipt and scoreboard routes and serves a statically exported Next.js front end (`apps/web`) from the same origin. agent.db becomes one shared, generation-guarded bucket object used by the CLI and the web alike.

**Tech Stack:** Python 3.13, FastAPI, uvicorn, `ag-ui-adk` 0.11.0, google-adk 2.12.0; Node 22 LTS, Next.js (App Router, static export), TypeScript strict, `@ag-ui/client`, Tailwind CSS, Radix primitives, Vitest + Testing Library, Playwright + `@axe-core/playwright`; Terraform; Cloud Run with IAP.

**Spec:** `docs/superpowers/specs/2026-10-30-phase-5-web-frontend-design.md` (approved 2026-10-30). Research: `docs/research/10-ag-ui-frontend.md`.

## Global Constraints

- Same agent as the CLI: `build_workflow()`, `ALL_TOOLS`, `costs` caps and receipts. The web adds no new intelligence.
- Pin exact versions of `ag-ui-adk` (0.11.0), `@ag-ui/client`, Next.js and every npm dependency, with a lockfile committed. Record each chosen version in the ledger.
- No raw tool rows in the stream: `TOOL_CALL_RESULT`, `MESSAGES_SNAPSHOT` and `STATE_SNAPSHOT` are filtered server-side (spec §12 call 2). Receipt data loads only via `GET /api/receipts/{id}`.
- No health data persisted in the browser: no localStorage or IndexedDB for data, and the service worker caches the app shell only.
- One agent.db: the bucket object is shared by the CLI, laptop web and cloud (spec §12 call 1). It is seeded once from the laptop file.
- Laptop mode binds `127.0.0.1` only and refuses any other Host header. Cloud mode sits behind IAP only (owner account).
- Model access: Vertex AI as the caller's identity. The free-tier key stays CI-only and synthetic-only. `--demo` serves the synthetic eval fixture and shows a "demo data" badge. Every public screenshot uses demo mode.
- Model text renders as text (Markdown with raw HTML disabled). Strict CSP, no third-party scripts.
- WCAG 2.2 AA: keyboard, visible focus, `aria-live="polite"` for streaming text, contrast in light and dark, reduced motion.
- Visual direction (spec §7a): sporty athletic-performance data look, built with Claude's `frontend-design` skill. The owner picks one of 2–3 mockups before screens are built.
- Cloud spend under $1/month in total. Personal accounts only. Deploy needs the owner's yes.
- No real health data in the repo, CI, fixtures or screenshots.

## Amendments after Phase 4.5 (2026-10-31)

Phase 4.5 changed the agent after this plan was written. These override the tasks below.

- **Topologies.** `multi` is now an alias of `team`: one agent with a coach and a domain expert as `AgentTool`s (ADR 0007). Task 1's multi test becomes `test_team_topology_streams_and_may_call_a_specialist`; there is no router or synthesizer.
- **Unbacked numbers.** The `unverified:` footer is gone. The answer may end with a quiet note, `_Note: N figure(s) wasn't/weren't computed by a tool: X._`, parsed by `health_agents.verify.unbacked_in`. Task 5 parses that note (and still the legacy footer); Task 7's `UnverifiedNote` shows it as a quiet note, not a warning.
- **Live location (owner requirement).** The browser asks for the device location once (with the user's permission) and sends `{latitude, longitude, place?}` in the AG-UI run's `state.location`. The server copies only those numeric keys into the ADK session state `location`, which the `weather` tool already reads; the model never sees or sets it. If permission is refused, the home location (Erode) is used. New Task 3a below.
- **14 tools.** `ALL_TOOLS` has 14 entries (13 plus ADK `load_memory`); the timeline labels each.
- **Detail tables.** Receipts may be SQL over `sleep_sessions`, `exercise_sessions`, `night_vitals`, `activity_breakdown` or `weather_daily`; `describe_receipt` names them.

### Task 3a: Device location into session state

**Files:** Modify `src/health_web/agent.py` (or `app.py`); Test `tests/test_web_location.py`

- [ ] **Step 1: Failing tests:**
  - `test_location_from_run_state_reaches_weather_tool`: a run whose `state.location` is `{"latitude": 13.08, "longitude": 80.27, "place": "Chennai"}` makes the `weather` tool request those coordinates (fake `weather.forecast`);
  - `test_location_is_sanitised`: non-numeric or out-of-range values (|lat| > 90, |lon| > 180), extra keys and a `place` longer than 60 characters are dropped or trimmed; nothing else from client state reaches the session;
  - `test_no_location_uses_home`.
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5:** Commit `feat(web): device location for the weather tool, from trusted session state`.

In the front end (Task 7), `navigator.geolocation.getCurrentPosition` runs once per session after a visible "Use my location for weather" choice; a refusal is remembered for the session only.

## Review Focus

1. **A run that errors mid-answer** (quota, budget reached, network) → the partial text stays, marked "incomplete", with the error explained in plain words; never a blank screen or a silent stop. → Task 7 `test_run_error_keeps_partial_answer_marked_incomplete`.
2. **A receipt id that doesn't exist** (typed by the model, or from a reset agent.db) → the panel says "No such receipt" and the chat keeps working. → Task 3 `test_unknown_receipt_is_404_with_message`, Task 8 `ReceiptPanel shows not-found state`.
3. **Model text containing HTML or a script tag** → rendered as literal text. → Task 7 `test_answer_html_is_rendered_as_text`.
4. **Two writers pushing agent.db at once** (phone and laptop) → the loser re-pulls, re-appends its rows and pushes once more; if that fails, "This answer was not saved". → Task 4 `test_push_race_reappends_once_then_reports`.
5. **An approve card after the server restarted** (scale-to-zero) → "This conversation expired. Ask again." and nothing saved. → Task 1 `test_resume_unknown_thread_is_expired`, Task 8 `ApproveCard shows expired state`.

---

## File Structure

```
packages/health_web/                 new Python package (cha-web)
  pyproject.toml
  src/health_web/
    app.py          create_app(mode) -> FastAPI: agent endpoint, routes, static, headers
    agent.py        build_agent(mode, model=None) -> ag-ui-adk agent over build_workflow
    stream.py       filter_events(): strip raw rows from AG-UI events
    routes.py       receipts (+ description, rerun), scoreboard, health
    describe.py     describe_receipt(receipt) -> plain-language line
    cli.py          `cha-web [--demo] [--port 8780]`
packages/health_agents/src/health_agents/
    agent_db_sync.py   shared agent.db: pull_agent_db / push_agent_db (guarded, re-append)
apps/web/                            Next.js app (static export into apps/web/out)
  app/(chat)/page.tsx, app/scoreboard/page.tsx, app/manifest.ts
  components/  Chat, AgentTimeline, ReceiptChip, ReceiptPanel, MetricCard, ApproveCard,
               UnverifiedNote, ErrorBanner, DemoBadge
  lib/agent.ts     useAgentRun(): @ag-ui/client wrapper -> UI state
  lib/types.ts     the AG-UI events we consume, filtered shapes
  public/sw.js     app-shell-only service worker
  tests/ (Vitest), e2e/ (Playwright)
apps/webservice/Dockerfile           image: Python app + built front end
infra/web.tf                         Cloud Run service + IAP + agent.db IAM
.github/workflows/web.yml            lint, types, unit, e2e (fake model)
tests/test_web_*.py                  backend tests (pytest, FakeLlm)
```

---

### Task 1: ag-ui-adk over the real workflows (risk spike, kept)

**Files:** Create `packages/health_web/pyproject.toml`, `src/health_web/agent.py`, `src/health_web/app.py` (minimal); Modify root `pyproject.toml` (workspace member + dependency); Test `tests/test_web_agent.py`

**Interfaces:**
- Consumes: `health_agents.workflow.build_workflow(topology, model=..., tools=...)`, `health_agents.cli.APP_NAME`, `health_agents.memory.HealthMemoryService`, `health_eval.runner.eval_fixture` (tests only), `agent_fakes.FakeLlm`.
- Produces: `build_agent(*, topology: str | None = None, model: BaseLlm | str | None = None) -> ADKAgent` (via `ADKAgent.from_app(App(name=APP_NAME, root_agent=build_workflow(...), resumability_config=ResumabilityConfig(is_resumable=True)), user_id="owner", memory_service=HealthMemoryService())`); `create_app(mode: Literal["local","demo","cloud"], *, model=None) -> FastAPI` with `POST /api/agent`.

- [ ] **Step 1: Failing tests** with FastAPI `TestClient` streaming `POST /api/agent` (a `RunAgentInput` JSON) on the eval fixture:
  - `test_single_topology_streams_run_text_and_tool_events`: event types include `RUN_STARTED`, `TOOL_CALL_START` (name `run_sql`), `TEXT_MESSAGE_CONTENT`, `RUN_FINISHED`, and the concatenated text contains the receipt id the tool produced;
  - `test_multi_topology_streams_through_router_and_specialist`: fake router JSON → data_scientist → synthesizer; ends with `RUN_FINISHED`;
  - `test_save_fact_surfaces_confirmation_and_resume_saves_only_on_approve`: `adk_request_confirmation` tool call appears; resuming with `{"confirmed": false}` saves nothing (facts table count 0), with `true` saves one;
  - `test_resume_unknown_thread_is_expired`: a resume for an unknown thread returns an AG-UI `RUN_ERROR` whose message is `"This conversation expired. Ask again."`.
- [ ] **Step 2:** Run `uv run pytest tests/test_web_agent.py -q` → FAIL (package missing).
- [ ] **Step 3:** Implement `agent.py` and the minimal `app.py` (`add_adk_fastapi_endpoint(api, agent, path="/api/agent")`). Add dependencies `fastapi`, `uvicorn`, `ag-ui-adk==0.11.0` to `health_web` only. If a test exposes an ag-ui-adk incompatibility, apply the smallest adapter in `agent.py` and ledger the ruling. If it cannot work, stop and report (a plan-level blocker).
- [ ] **Step 4:** Run → PASS. `ruff check`, `pyright` clean.
- [ ] **Step 5:** Commit `feat(web): serve the ADK workflow over AG-UI`.

### Task 2: Stream filter (no raw rows to the browser)

**Files:** Create `src/health_web/stream.py`; Modify `agent.py`/`app.py` to route events through it; Test `tests/test_web_stream.py`

**Interfaces:**
- Produces: `filter_event(event: BaseEvent) -> BaseEvent | None`.
  - `TOOL_CALL_RESULT` content becomes JSON `{"tool": str, "receipt": str | None, "status": "ok" | "error", "n": int | None, "error": str | None}`.
  - `STATE_SNAPSHOT` / `STATE_DELTA` keep only the keys `turn_receipts` and `verify_attempts`.
  - `MESSAGES_SNAPSHOT` tool messages are reduced the same way as tool results.
  - Everything else passes through.
- [ ] **Step 1: Failing tests:**
  - `test_tool_result_keeps_receipt_drops_rows`: a run_sql result with rows `[{"n": 41}]` → content has `receipt` and `n == 1`, and the string `41` is absent;
  - `test_state_snapshot_allowlist` (`turn_outputs` absent);
  - `test_messages_snapshot_tool_content_reduced`;
  - `test_end_to_end_stream_has_no_fixture_values`: a full streamed run over the fixture contains none of a set of distinctive fixture values (the resting-heart-rate rows) except where the model's own answer text states them.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (wrap the agent's event iterator; never mutate ADK state). **Step 4:** Run → PASS. **Step 5:** Commit `feat(web): filter raw tool rows out of the AG-UI stream`.

### Task 3: Receipt, scoreboard and health routes; laptop and demo modes

**Files:** Create `src/health_web/routes.py`, `describe.py`, `cli.py` (`cha-web`); Modify `app.py`; Test `tests/test_web_routes.py`

**Interfaces:**
- Produces:
  - `GET /api/receipts/{id}` → `{id, kind, executor, as_of, code, output, data_hash, description, where}`, or 404 `{"error": "No such receipt"}`;
  - `POST /api/receipts/{id}/rerun` → `{status: "matches" | "differs" | "data_changed" | "error", detail}`, reusing `health_agents.receipts.get/rerun`;
  - `GET /api/scoreboard` → `health_ledger.publish.public_board(scoreboard.build(conn))`, with rows below 10 days marked `"not_yet": true` (the Task 16 rule);
  - `GET /api/health` → `{"ok": true, "mode": ...}`;
  - `describe_receipt(kind: str, code: str) -> str`, for example "SQL over daily resting heart rate".
  - `cha-web [--demo] [--port 8780] [--host 127.0.0.1]`. Local and demo modes refuse a Host header other than `127.0.0.1`/`localhost` with 403, like `health_eval.review`. Demo mode builds the eval fixture via `health_eval.runner.eval_fixture` (lazy import) and sets `/api/health` `demo: true`.
- [ ] **Step 1: Failing tests:**
  - `test_receipt_route_returns_code_output_and_description`;
  - `test_unknown_receipt_is_404_with_message`;
  - `test_rerun_reports_matches`;
  - `test_scoreboard_marks_not_yet_below_ten`;
  - `test_local_mode_refuses_foreign_host`;
  - `test_demo_mode_uses_fixture_and_flags_demo`;
  - `test_describe_receipt_names_tables_and_types` (parametrised: SQL over `daily_metrics` with a `data_type` literal; python code → "Python over your …"; unknown → "SQL query" / "Python computation").
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5:** Commit `feat(web): receipt, re-run and scoreboard routes; cha-web laptop and demo modes`.

### Task 4: One shared agent.db in the bucket

**Files:** Create `packages/health_agents/src/health_agents/agent_db_sync.py`; Modify `agent_db.py` (docstring: no longer laptop-only), `health_core/settings.py` (`agent_db_object: str = "agent.db"`), `cli.py` (Session pulls before and pushes after a turn when `CHA_DB_BUCKET` is set; `cha agentdb seed`), `health_web/app.py` (same hook per turn); Test `tests/test_agent_db_sync.py`

**Interfaces:**
- Produces:
  - `pull_agent_db(bucket, obj, dest, *, client=None) -> int | None`;
  - `push_agent_db(bucket, obj, src, *, since: dict[str, int], client=None) -> Literal["pushed", "reappended", "not_saved"]`, where `since` holds the max rowids per append-only table (`receipts`, `chat_usage`, `facts`, `episodes`) captured before the turn;
  - `snapshot_rowids(conn) -> dict[str, int]`.

  On a generation conflict: re-pull, re-insert this turn's rows (rowid > since), push once more. A second conflict returns `"not_saved"`. It reuses `health_data.store` guards and the fake client from the store tests.
- [ ] **Step 1: Failing tests:**
  - `test_pull_then_push_round_trip`;
  - `test_push_race_reappends_once_then_reports` (fake client bumps the generation once → `"reappended"`, rows from both writers present; bumps twice → `"not_saved"`);
  - `test_cli_turn_pulls_and_pushes_when_bucket_set` (FakeLlm);
  - `test_seed_refuses_when_object_exists`.
- [ ] **Step 2–4:** FAIL → implement → PASS (full suite green: the CLI changed). **Step 5:** Commit `feat(agents): one shared agent.db in the bucket for CLI and web`.

### Task 5: Front-end scaffold and AG-UI client

**Files:** Create `apps/web/` (Next.js App Router, `output: "export"`, TypeScript strict, ESLint, Prettier, Tailwind, Vitest, Playwright config), `lib/types.ts`, `lib/agent.ts`; Modify `health_web/app.py` (serve `apps/web/out` at `/`, falling back to a "build the front end" page when missing); Create `.github/workflows/web.yml` (npm ci, lint, typecheck, vitest; the e2e job is added in Task 10); Test `apps/web/tests/agent.test.ts`

**Interfaces:**
- Produces: `useAgentRun()` → `{messages: UiMessage[], steps: AgentStep[], status: "idle" | "running" | "awaiting_approval" | "error" | "done", error?: UiError, ask(text), approve(), deny()}`.
  - `UiMessage = {id, role, text, receipts: string[], unverified: string[] | null, incomplete: boolean, usd?: number}`.
  - `AgentStep = {id, tool, label, status, receipt?: string, n?: number}`.
  - Receipt ids are parsed from text with `/\br-[0-9a-f]{10}\b/`, and the `unverified:` footer is split from the answer.
- [ ] **Step 1: Failing tests** (Vitest, feeding recorded filtered event sequences):
  - `builds a message with receipts from text deltas`;
  - `splits the unverified footer`;
  - `tool events become timeline steps`;
  - `confirmation tool call sets awaiting_approval`;
  - `RUN_ERROR keeps partial text and marks it incomplete`.
- [ ] **Step 2–4:** FAIL → implement → PASS. `npm run lint && npm run typecheck` clean. **Step 5:** Commit `feat(web-ui): Next.js scaffold and AG-UI client hook`.

### Task 6: Visual direction (owner gate)

**Files:** Create `apps/web/design/mockups/` (2–3 static HTML or TSX mockups on the synthetic fixture), `apps/web/app/tokens.css` (after the pick)

- [ ] **Step 1:** Load Claude's `frontend-design` skill. Produce 2–3 distinct directions in the spec §7a world (race telemetry, training log, watch face). Each shows the chat with a streaming answer, the agent-at-work timeline, a sleep metric card with its receipt chip, and an open receipt panel, in dark and light, at desktop and phone widths.
- [ ] **Step 2:** Show them to the owner (screenshots, or a local page). **Stop until the owner picks one.** Ledger the pick.
- [ ] **Step 3:** Write the chosen direction as tokens (color, type, spacing, radius, motion) in `tokens.css`, plus the Tailwind theme. It must meet contrast in both themes (checked in Task 10 by axe).
- [ ] **Step 4:** Commit `feat(web-ui): visual system (owner-picked direction)`.

### Task 7: Chat screen

**Files:** Create `components/Chat.tsx`, `AgentTimeline.tsx`, `ReceiptChip.tsx`, `UnverifiedNote.tsx`, `ErrorBanner.tsx`, `DemoBadge.tsx`, `app/(chat)/page.tsx`; Test `apps/web/tests/chat.test.tsx`

**Interfaces:** consumes `useAgentRun()`. The disclosure copy is exactly `health_agents.cli.DISCLOSURE`. Answers render through a Markdown renderer with raw HTML disabled.

- [ ] **Step 1: Failing tests:**
  - `renders streamed answer with receipt chips`;
  - `timeline shows each tool step with its status`;
  - `unverified footer renders as a warning`;
  - `test_answer_html_is_rendered_as_text` (`<script>` appears as text, no script element);
  - `test_run_error_keeps_partial_answer_marked_incomplete` (budget, quota and network copy);
  - `shows disclosure and per-answer cost`;
  - `streaming region is aria-live polite`.
- [ ] **Step 2–4:** FAIL → implement in the Task 6 visual system → PASS. **Step 5:** Commit `feat(web-ui): chat screen with agent timeline and receipt chips`.

### Task 8: Receipt panel, metric card, approve card

**Files:** Create `components/ReceiptPanel.tsx`, `MetricCard.tsx`, `ApproveCard.tsx`, `lib/receipts.ts`; Test `apps/web/tests/receipts.test.tsx`

**Interfaces:**
- Consumes `GET /api/receipts/{id}` and `POST /api/receipts/{id}/rerun` (Task 3).
- `MetricCard` renders when a receipt's output is a list of rows with a date-like key and one numeric key. It shows a bar or line chart drawn to scale, the headline number and its chip. Data comes from the receipt route only.
- [ ] **Step 1: Failing tests:**
  - `ReceiptPanel shows description first, then code, output, as-of and data hash`;
  - `ReceiptPanel shows not-found state` (404);
  - `Re-run shows matches / differs / data changed`;
  - `MetricCard charts a date series to scale and skips non-series outputs`;
  - `ApproveCard approve and deny call the hook`;
  - `ApproveCard shows expired state` (the expired `RUN_ERROR` message).

  The panel is a side sheet at ≥ 768 px and a bottom sheet below, with focus trapped and Escape closing it.
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5:** Commit `feat(web-ui): receipt panel, metric cards and approval`.

### Task 9: Scoreboard page and PWA

**Files:** Create `app/scoreboard/page.tsx`, `app/manifest.ts`, `public/sw.js`, icons; Test `apps/web/tests/scoreboard.test.tsx`, `apps/web/tests/sw.test.ts`

- [ ] **Step 1: Failing tests:**
  - `scoreboard shows n beside every number and "not yet" below ten`;
  - `sw caches only app-shell paths and never /api/*` (unit-test the `sw.js` fetch handler with mocked caches);
  - `manifest has name, icons, display standalone, theme color`.

  The manifest link uses `crossorigin="use-credentials"` (research §5).
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5:** Commit `feat(web-ui): scoreboard page and installable app shell`.

### Task 10: End-to-end, accessibility, CI

**Files:** Create `apps/web/e2e/flow.spec.ts`; Modify `health_web/cli.py` (`--test-model` flag: FakeLlm script from `CHA_WEB_FAKE_SCRIPT`, refused unless `--demo`); Modify `.github/workflows/web.yml` (build export, start `cha-web --demo --test-model`, run Playwright with axe)

- [ ] **Step 1: Failing e2e:** `ask → stream → timeline → open receipt → re-run matches → metric card visible → approve a fact`, at 1280×800 and 390×844, in light and dark. Axe: no serious or critical violations on chat, receipt panel and scoreboard.
- [ ] **Step 2–4:** FAIL → implement the missing wiring → PASS locally and in CI. **Step 5:** Commit `test(web): end-to-end flow and accessibility in CI`.

### Task 11: Security headers and tracing

**Files:** Modify `health_web/app.py`; Test `tests/test_web_security.py`

- [ ] **Step 1: Failing tests:**
  - `test_security_headers`: a CSP of `default-src 'self'`, no inline script, `frame-ancestors 'none'`, with connect-src self; plus `X-Content-Type-Options`, `Referrer-Policy`;
  - `test_request_span_has_no_body` (in-memory exporter: a `cha.web.request` span with route and status, and the question absent);
  - `test_tracing_setup_called_once`.
- [ ] **Step 2–4:** FAIL → implement (middleware; `tracing.setup()` at startup) → PASS. **Step 5:** Commit `feat(web): security headers and request tracing`.

### Task 12: Milestone 1 exit check and docs

**Files:** Modify `README.md` ("Ask it" gains the web screenshot from demo mode, plus run instructions), `docs/observability.md` (web span); Create `docs/web.md` (how to run, modes, security model)

- [ ] **Step 1:** Seed the shared agent.db (`cha agentdb seed`, owner's account). Run `uv run cha-web` on the laptop against real data. Ask "How did I sleep this week?", open its receipt, re-run → matches. Record the result in the ledger (no real values).
- [ ] **Step 2:** Capture publishable screenshots with `cha-web --demo` (desktop and phone, dark and light) into `docs/images/web-*.png`.
- [ ] **Step 3:** Docs. Full suite, ruff, pyright, `npm run lint`, typecheck, vitest all clean. **Step 4:** Commit `docs(web): laptop milestone, screenshots and run guide`.

### Task 13: Cloud Run with IAP (milestone 2, owner's yes)

**Files:** Create `apps/webservice/Dockerfile` (multi-stage: Node build of `apps/web` → Python `uv sync --package health-web`, non-root, `cha-web --host 0.0.0.0 --mode cloud`), `infra/web.tf`; Modify `infra/iam.tf`, `infra/variables.tf`; Test `tests/test_web_infra.py` (parse `web.tf`: `iap_enabled`, owner-only `roles/iap.httpsResourceAccessor`, min instances 0, timeout 600 s, no `allUsers`)

- [ ] **Step 1:** Failing infra test → write Terraform → PASS. `terraform validate` and fmt clean.
- [ ] **Step 2:** **Ask the owner for a yes.** Build and push the image, then `terraform apply` (personal account).
- [ ] **Step 3: Exit check:**
  - `curl -N` through IAP shows events arriving incrementally (risk 2);
  - a signed-out request is refused;
  - on the phone, signed in and installed to the home screen, the Task 12 flow works (risk 3);
  - record cold-start time (risk 4).
- [ ] **Step 4:** Commit `feat(infra): web service on Cloud Run behind IAP`.
