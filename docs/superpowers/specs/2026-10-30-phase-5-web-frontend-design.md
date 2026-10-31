# Phase 5: web front end (design)

Status: **approved by the owner 2026-10-30**, with the visual-direction requirement in §7a.
Research: `docs/research/10-ag-ui-frontend.md` (AG-UI, ag-ui-adk, CopilotKit, IAP, PWA).
Builds on: Phase 3 agent (`health_agents.cli.Session`, `workflow.build_workflow`), Phase 4
evals and tracing.

## 1. Intent

A web page where the owner talks to the agent and checks its work: ask a question in plain
language ("how did I sleep this week?"), watch the answer stream in, and tap any receipt to see
the code and data behind a number. It replaces the terminal (`cha ask`) as the front door, and
it is the portfolio's demo surface. The owner's words: "I just want to test our agent from
here; the front end should follow standard practices."

The agent is the product. The front end exposes what the agent already does (tools, receipts,
the verify step, memory confirmation) and adds no new intelligence.

## 2. Goals

1. **Chat with the real agent** from a browser on the laptop, and later from the phone.
2. **Answers stream**, and the steps the agent takes are visible as they happen (which tool,
   then the result), so a reader sees an agent working, not a chatbot replying.
3. **Every receipt is clickable.** A receipt id in an answer opens a panel with the receipt's
   kind (SQL / Python), code, output, as-of date, and a **Re-run** button that reports
   "matches" or "differs".
4. **Memory confirmation** (`save_fact`, `require_confirmation=True`) appears as an approve /
   deny card. Nothing is saved without approve.
5. **`unverified:` footers** are shown as a distinct warning, never hidden.
6. **Scoreboard view:** the same aggregates the public scoreboard shows, read-only.
7. **Standard engineering practice:** typed end to end, linted, unit and end-to-end tests in CI,
   accessible (WCAG 2.2 AA), responsive, installable as a PWA.
8. **Runs locally first, then in the cloud**, behind Google sign-in, for under $1/month.

## 3. Non-goals

- More than one user, sign-up, or sharing. The owner is the only user.
- Editing data, writing the journal from the web (the Google Form stays), deleting memory.
- Embedding inside Google's Health / Fitbit app (not possible).
- An MCP server (dropped 2026-10-30).
- Push notifications, offline answers (the agent needs the network), native mobile apps.
- A new design system or a marketing site. The README stays the landing page.

## 4. Anti-goals (failure even if it "works")

- Health data reachable without the owner's sign-in, even for one request.
- Health data persisted in the browser (localStorage, IndexedDB, the service worker cache).
  The PWA caches the app shell only.
- The UI implying a number is checked when it isn't (a lost `unverified:` footer, a receipt
  chip on a number that has none).
- A different agent behind the web than behind `cha ask`. Same `build_workflow`, same tools,
  same caps.
- Cost creeping above the $1/month budget (always-on instances, a load balancer, a database
  server).

## 5. Architecture (decided)

One service, same origin:

```
browser (Next.js static export, @ag-ui/client)
   │  POST /api/agent  (AG-UI RunAgentInput)  ← SSE stream of AG-UI events
   │  GET  /api/receipts/{id}   POST /api/receipts/{id}/rerun
   │  GET  /api/scoreboard
   ▼
FastAPI app (new package `apps/web` or `packages/health_web`, builder's call on the name)
   ├─ ag-ui-adk ADKAgent.from_app(App(root_agent=build_workflow(...), resumability on))
   ├─ receipts + scoreboard routes reuse health_agents.receipts / health_ledger.scoreboard
   └─ serves the static front end at /
   ▼
health.db (read-only, pulled from the GCS bucket) + agent.db (receipts, usage, memory)
```

- **Backend:** FastAPI with `ag-ui-adk` pinned to an exact version (0.11.0 at research time),
  wrapping the **same** `build_workflow()` and tools as the CLI, through
  `ADKAgent.from_app(App(...))`. The direct `ADKAgent(adk_agent=...)` path doesn't accept a
  graph `Workflow` (research §2).
- **Front end:** Next.js (App Router, TypeScript strict) built as a **static export** and served
  by the same FastAPI app. One origin means one sign-in cookie, no CORS and one cold start.
  The plain `@ag-ui/client` SDK with our own React components; **not CopilotKit**, because its
  supported setup needs a separate Node server (research §3).
- **UI kit:** Tailwind CSS plus a small set of accessible primitives (shadcn/ui or Radix). The
  builder may pick, as long as it stays one consistent kit.
- **Hosting (milestone 2):** one Cloud Run service, scale to zero, `--iap` (IAP directly on
  Cloud Run, no load balancer), access granted to the owner's Google account only, request
  timeout about 600 s, same project and Terraform as everything else.
- **Model access:** Vertex AI as the service's own identity (as the job does), never an API
  key. The free-tier key stays CI-only and synthetic-only.

## 6. Data and state

- **health.db:** pulled read-only from the bucket on cold start and refreshed when the bucket
  generation changes (the job keeps writing it). The service never pushes health.db.
- **agent.db (receipts, chat usage, memory):** must outlive a Cloud Run instance, because
  receipts are re-runnable and the chat cap counts monthly spend. Decided: persist it to its own
  object in the private bucket with the same generation-guarded push the job uses. Pull on cold
  start, push after each turn that wrote something. Single user, so conflicts are rare and lose
  loudly.
- **Sessions:** one conversation per browser tab (`threadId`). ADK session state stays
  server-side (in memory, plus what the resumability config needs).
- **State snapshots:** AG-UI `STATE_SNAPSHOT` would send the whole session state to the
  browser, including `turn_outputs` (raw tool results). **Filter it server-side to an
  allowlist** (receipt ids for the turn, verify attempts). Raw rows reach the browser only
  through the receipt route, for one receipt at a time.
- **Laptop mode (milestone 1):** the same app runs locally (`uv run cha-web`) against the
  owner's local database, with no sign-in, bound to 127.0.0.1 only (like the review page).

## 7. Screens

1. **Chat (default):** message list, input box, streaming answer. Tool steps show inline as
   compact rows ("run_sql: average resting heart rate, last 7 days → receipt r-…").
   Receipt ids in the answer render as chips. An `unverified:` footer renders as a warning
   block. The AI disclosure line (same wording as the CLI) sits above the input. Cost and
   tokens per answer appear in small print.
2. **Receipt panel** (side sheet on desktop, bottom sheet on phone), opened from a chip or a
   tool row: the plain-language description of what was computed first (from the tool and
   question), then the code (syntax-highlighted), the output, as-of date and data hash, and a
   **Re-run** button showing matches / differs / data changed.
3. **Approve card** for `save_fact`: the fact text, Approve / Deny. It resumes the run.
4. **Scoreboard:** the aggregate scoreboard (n next to every number, "not yet" below 10 days,
   the same rounding rules as the public board).
5. **Errors:** budget reached, quota, network, and signed out, each with plain text that says
   what happened and what to do.

## 7a. Visual direction (owner requirement, 2026-10-30)

Screenshots of this front end will be published on Medium and LinkedIn, so it must not look
like a basic chat template. The owner asked for a **sporty** feel.

- **Direction:** athletic performance data, the visual world of race telemetry, training logs
  and sports-watch faces, not a generic chat app. Bold condensed display type for numbers and
  headings, tabular numerals everywhere, a high-energy accent used sparingly, and a dark theme
  that looks right in a screenshot (with a real light theme too). Motion is limited to the
  stream itself and small, purposeful transitions (respecting reduced motion).
- **Generative UI is the showcase.** This is where AG-UI earns its place on screen. When a
  turn's tool result is a time series, the answer carries an inline **metric card**: a small
  chart such as a sleep bar chart or a resting-heart-rate trend, plus the headline number and
  its receipt chip. Tool steps render as a live **"agent at work"** timeline. The data for a
  card loads through `GET /api/receipts/{id}` (call 2 in §12 still holds).
- **Use Claude's `frontend-design` skill** during implementation for the visual system
  (tokens, type pairing, layout, components), and avoid templated looks.
- **Pick a direction before building screens:** the builder produces two or three static
  mockups of the chat screen with a metric card and an open receipt panel (on the synthetic
  fixture). The owner picks one before the components are built.
- **Demo mode for publishing:** `cha-web --demo` serves the synthetic eval fixture, so every
  public screenshot and GIF shows synthetic data, never the owner's real health data. The
  page shows a small "demo data" badge in this mode.

## 8. Quality bar (standard practices)

- **Typing:** TypeScript strict, generated or hand-written types for the AG-UI events in use.
  The backend stays under pyright like the rest of the repo.
- **Lint and format:** ESLint (Next.js config) and Prettier for the front end, ruff for Python.
- **Tests:**
  - backend route tests with the fake model (`agent_fakes.FakeLlm`): streaming, receipt
    route, re-run, approve/deny resume, the state-snapshot allowlist, the 127.0.0.1 bind in
    laptop mode;
  - front-end component tests (Vitest + Testing Library);
  - Playwright end-to-end against the backend with the fake model: ask → stream → open
    receipt → re-run → approve a fact, at desktop and phone widths.

  All run in CI with no model and no credentials.
- **Accessibility:** WCAG 2.2 AA. Keyboard reachable, visible focus, streamed text announced
  politely (`aria-live`), contrast in light and dark, and respects reduced motion.
- **Security:** IAP in the cloud. Strict CSP and security headers. No third-party scripts.
  The model's text is rendered as text (Markdown with HTML disabled). The receipt route
  returns only receipts from this agent.db. Laptop mode binds 127.0.0.1 only.
- **Observability:** the existing tracing (`CHA_TRACING`). A `cha.web.request` span per
  request, content off in the cloud.
- **PWA:** web app manifest plus a minimal service worker that caches the app shell only.
  Installable on Android and iOS.
- **Performance:** first answer token visible within the model's own latency. A static front
  end, so no server rendering cost.

## 9. Milestones

1. **Laptop:** `cha-web` serves the app on 127.0.0.1 against local data. All screens work.
   Tests green. Exit check: ask "how did I sleep this week?", open its receipt, re-run →
   matches.
2. **Cloud:** Terraform adds the Cloud Run service with IAP (owner only), the agent.db object
   and its IAM; image built and pushed as for the job. Deploy needs the owner's yes. Exit
   check: the same flow on the phone, signed in, with the app installed to the home screen,
   and a signed-out request refused.

## 10. Constraints

- Cloud spend stays under $1/month in total (expected about $0–0.20 for hosting, plus model
  tokens inside the existing $0.30 chat cap, which also covers web chat).
- Personal accounts only (GitHub kb2326, gcloud `personal` configuration).
- Pin exact versions of `ag-ui-adk`, `@ag-ui/client` and Next.js. ag-ui-adk changed breaking
  APIs weekly in October 2026.
- No real health data in the repo, CI, test fixtures or screenshots. Demo screenshots use the
  synthetic fixture.

## 11. Risks to retire early (from the research)

1. ag-ui-adk with our **real multi-node** workflows (single and multi topology), memory
   service and confirmation flow. Spike this first, offline with the fake model.
2. Whether IAP or Cloud Run buffers the SSE stream (`curl -N` through IAP).
3. iOS home-screen app sign-in behaviour behind IAP.
4. Cold-start time for the image (pulling health.db + agent.db).

## 12. Calls made after the builder check (author's calls, not the owner's)

1. **One agent.db, shared.** The bucket object is the single source for receipts, chat spend
   and memory. `cha ask`, laptop `cha-web` and the cloud service all pull it before a turn and
   push it after, with the generation guard. It is seeded once by uploading the laptop's
   existing agent.db. Why: one agent, one $0.30 cap, one memory, and receipts that resolve
   everywhere. If a push loses the race, re-pull and re-append this turn's rows (receipts,
   usage and memory are append-only), then push again once. If that also fails, tell the user
   "this answer was not saved". This updates the `agent_db.py` "laptop-only" note.
2. **The stream carries no raw rows either.** The server filters `TOOL_CALL_RESULT` and
   `MESSAGES_SNAPSHOT` (as well as `STATE_SNAPSHOT`) down to tool name, receipt id, status
   and row count. The receipt panel always loads through `GET /api/receipts/{id}`. Why: the
   strict reading of §6 is the safe one, and it gives one code path for live and older
   receipts. It costs a wrapper around ag-ui-adk's event stream, with tests.
3. **Conversations don't survive a reload or a cold start.** Sessions stay in memory. A
   reload shows an empty chat. A stale approve card or resume shows "This conversation
   expired. Ask again." Why: single user, simplest correct behaviour, and no raw rows
   persisted in a second store.
4. **The receipt description is derived from the receipt itself**: kind, plus tables or data
   types named in the code (for example "SQL over daily resting heart rate"). There is no
   schema change, and the same rule works for investigator receipts. When the receipt comes
   from the current turn, the tool name is added.

## 13. Left to the builder

Package and folder names; UI kit (Tailwind + shadcn/ui or Radix); the code highlighter; how the
plain-language receipt description is produced (a template from the tool name and arguments,
not a model call); the exact tool-step row wording; the PWA icon set.
