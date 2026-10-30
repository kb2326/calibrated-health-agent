# 10 — Web front end: Next.js + AG-UI over the ADK workflow

Researched 2026-10-30 for the web app phase. Goal: a single-user (owner) web front end to the
existing ADK 2.12 graph `Workflow`: streaming answers, clickable receipts (`r-…` → SQL/Python
behind a number), a forecast scoreboard view, installable as a PWA, Google sign-in, Cloud Run
behind IAP, under $1/month.

Marks: **[verified]** primary source fetched, or checked by running code ·
**[secondary]** search results or summaries · **[prior]** the researcher's prior knowledge.
Re-check anything not verified before relying on it.

---

## 1. AG-UI protocol

An open, event-based protocol between an agent backend and a user-facing app. The client
POSTs a `RunAgentInput` (`threadId`, `runId`, `messages`, `state`, `tools`, `context`,
`forwardedProps`, optional `resume`). The server streams typed JSON events back, usually as
SSE over HTTP. https://docs.ag-ui.com/concepts/events [verified]

| Group | Events |
|---|---|
| Lifecycle | `RUN_STARTED`, `RUN_FINISHED`, `RUN_ERROR`, `STEP_STARTED`, `STEP_FINISHED` |
| Text | `TEXT_MESSAGE_START` / `_CONTENT` / `_END` (+ `_CHUNK` convenience) |
| Tool calls | `TOOL_CALL_START` / `_ARGS` / `_END` / `_RESULT` (+ `_CHUNK`) |
| State | `STATE_SNAPSHOT`, `STATE_DELTA` (JSON Patch, RFC 6902), `MESSAGES_SNAPSHOT` |
| Activity | `ACTIVITY_SNAPSHOT`, `ACTIVITY_DELTA` |
| Reasoning | `REASONING_START`, `REASONING_MESSAGE_*`, `REASONING_END`, `REASONING_ENCRYPTED_VALUE` (the `THINKING_*` events are deprecated) |
| Sub-agents | `SUBAGENT_STARTED` / `_FINISHED` / `_ERROR` |
| Special | `RAW`, `CUSTOM` |

**Interrupts (human in the loop)** https://docs.ag-ui.com/concepts/interrupts [verified]. There is no
separate interrupt event. `RUN_FINISHED.outcome = {type: "interrupt", interrupts: [...]}`, and each
`Interrupt` has `id`, `reason` (`tool_call` | `confirmation` | …), `message`, `toolCallId`,
`responseSchema`, `expiresAt`, and `metadata`. The client resumes with a new run on the same
thread whose `resume: [{interruptId, status: "resolved"|"cancelled", payload}]` addresses
**every** open interrupt. A denial is a payload (`approved: false`), not a status. The events
page still marks the extended `RUN_FINISHED` fields (`outcome`, `result`) as **draft**.

**Versions:** the wire reports `protocolVersion: "1.0"` in `RUN_STARTED` (seen in the smoke test
below). The SDKs are `ag-ui-protocol` 1.0.0 (PyPI), and `@ag-ui/client` and `@ag-ui/core` 1.0.3,
MIT, published 2026-10-16 (npm). [verified]

## 2. ADK → AG-UI: `ag-ui-adk` (official, in the ag-ui repo)

- Package `ag-ui-adk` **0.11.0, released 2026-10-21**. Requires `google-adk>=1.28.1,<3.0.0` and
  Python `>=3.10,<3.16`. Source: `ag-ui-protocol/ag-ui/integrations/adk-middleware/python`.
  https://pypi.org/project/ag-ui-adk/ ,
  https://github.com/ag-ui-protocol/ag-ui/tree/main/integrations/adk-middleware/python [verified]
- API: `ADKAgent.from_app(app, user_id=..., session_service=..., emit_interrupt_outcome=...)`
  plus `add_adk_fastapi_endpoint(fastapi_app, agent, path="/agent",
  extract_state_from_request=...)`. It sets `StreamingMode.SSE` on the ADK `RunConfig`, so
  Gemini tokens stream as `TEXT_MESSAGE_CONTENT` deltas. [verified, source read]
- **ADK 2.x `Workflow` support.** The changelog has explicit Workflow handling:
  - 0.7.0 (2026-06-22): "an ADK 2.x `Workflow`'s child agents live in `workflow.graph.nodes`";
    `adk_request_confirmation` responses go through the `new_message` path.
  - The source has `_root_agent_is_workflow()` (ag-ui#1669), so a resumed Workflow does not
    restart from START.
  - 0.11.0: "Updated test compatibility for google-adk 2.12".
  - Caveat from the README: "Google ADK 2.x has a separate informational full-suite job with
    **known failures**". The locked CI environment is ADK 1.35.0. [verified]
- **Use `from_app`, not `ADKAgent(adk_agent=workflow)`.** The direct path builds
  `Runner(agent=...)`, which is typed `BaseAgent`. A `Workflow` is a `BaseNode`, not a
  `BaseAgent`. In ADK 2.12, `App.root_agent` is typed `BaseNode`, so
  `App(root_agent=build_workflow(...), resumability_config=ResumabilityConfig(is_resumable=True))`
  is the supported route. `ResumabilityConfig` still warns that it is EXPERIMENTAL. [verified locally]
- **Smoke test** (scratch venv: google-adk 2.12.0 + ag-ui-adk 0.11.0, Python 3.13, fake LLM, a
  `Workflow(edges=[("START", LlmAgent)])`, and `FunctionTool(save_fact, require_confirmation=True)`) [verified]:
  - Run 1 emits `TOOL_CALL_*` for `save_fact`, then a `TOOL_CALL_*` named
    `adk_request_confirmation` whose args carry `originalFunctionCall` and
    `toolConfirmation.hint`, then `STATE_SNAPSHOT` and `RUN_FINISHED`.
  - Run 2 sends that tool call back plus a `ToolMessage` with `{"confirmed": true}`. The tool
    executed (`TOOL_CALL_RESULT` with the receipt), and the text streamed with `[r-1a2b3c4d5e]`
    intact.
  - With `emit_interrupt_outcome=True`, `RUN_FINISHED.outcome` is
    `{type:"interrupt", interrupts:[{reason:"confirmation", toolCallId, metadata.adk.originalFunctionCall}]}`.
    In that mode the client **must** resume via `resume[]`; a plain tool message is rejected
    (`INTERRUPT_RESUME_REQUIRED`, since 0.7.1/0.8.0).
  - Not tested: the real multi-node `health_agent_single` / `multi` workflows, the real
    Gemini model, `load_memory` and the custom `HealthMemoryService`.
- **State.** `STATE_SNAPSHOT` / `STATE_DELTA` mirror the ADK session state, which adds
  `_ag_ui_*` keys. Since 0.11.0, client-supplied `app:` / `user:` state keys are discarded, and
  trusted values must come from `extract_state_from_request`. `turn_outputs` (the
  verification list) would be streamed to the browser. Fine for one user, but strip it or
  rename it if it gets large.
- **Sessions.** The default is in-memory, so sessions are lost on scale-to-zero. Any ADK
  `BaseSessionService` can be passed. `DatabaseSessionService` is explicitly exercised by the
  0.9.0 and 0.11.0 fixes.
- An alternative third-party package exists: `adk-agui-middleware` (Trend Micro). It is not
  needed. https://pypi.org/project/adk-agui-middleware/ [secondary]

## 3. Front-end clients

| | CopilotKit | `@ag-ui/client` (plain) |
|---|---|---|
| Version | 1.83.0 stable (2026-10-28). **2.0.0-rc.6 published 2026-10-30**: v2 is being cut now | 1.0.3 (2026-10-16) |
| License | MIT | MIT |
| Server piece | Recommended: a Node `CopilotRuntime` (`@copilotkit/runtime/v2`, `createCopilotRuntimeHandler`) in a Next.js route, proxying to an `HttpAgent`. A direct browser→agent path exists only as `agents__unsafe_dev_only` ("intended for development and prototyping") | None. `HttpAgent({url})` → `runAgent()` or subscribe to events from the browser |
| Generative UI | v2: `useRenderTool` (by tool name or `"*"`), `useFrontendTool`, `useHumanInTheLoop` (`respond()`), `useComponent`, `useAgent`. Prebuilt chat UI | You write it: a reducer over events; render a receipt card on `TOOL_CALL_RESULT`, and an approve/reject card on `adk_request_confirmation` |
| Next.js App Router | Yes (client components and an API route) | Yes. Works under `output: "export"` because it is just fetch + SSE |

Sources: https://docs.copilotkit.ai/adk , https://docs.copilotkit.ai/reference/hooks/useRenderToolCall ,
https://adk.dev/integrations/copilotkit/ (ADK docs page: `ag-ui-adk` + `@copilotkit/react-core`,
`@copilotkit/runtime`, `@ag-ui/client`; examples use `ADKAgent.from_app` + `ResumabilityConfig`),
https://docs.copilotkit.ai/ag2/backend/copilot-runtime (direct-connection caveat) [verified / secondary for the last].
npm versions from `npm view` on 2026-10-30 [verified]. Next.js is 16.4.3 stable.

Receipts fit AG-UI naturally. Each `TOOL_CALL_RESULT` carries the tool output, including the
SQL/Python and the receipt id. The UI can index results by receipt id and turn `[r-…]` tokens
in the streamed text into links that open the matching result. No new backend endpoint is
needed for in-session receipts. A `GET /receipts/{id}` endpoint is only needed for old sessions.

## 4. Hosting

- **IAP directly on Cloud Run (no load balancer) is GA.** The Cloud Run blog post (dated
  2026-03-13/14 in sources) and the Cloud Run release notes say GA. IAP is "no additional cost …
  with some exceptions". Enable with `gcloud run deploy … --no-allow-unauthenticated --iap`, then
  grant `roles/run.invoker` to `service-PROJECT_NUMBER@gcp-sa-iap.iam.gserviceaccount.com`.
  - A project with **no organization** (personal account) needs a one-time IAP/OAuth setup in
    the Console, because "you cannot create OAuth clients programmatically".
  - IAP cannot be on both the load balancer and the service.
  - CORS preflight `OPTIONS` can pass unauthenticated.
  https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run ,
  https://cloud.google.com/blog/products/serverless/iap-integration-with-cloud-run [verified].
  IAP pricing exceptions not read (the pricing page fetch was truncated) [unverified].
- **Streaming.** "Cloud Run supports streaming HTTP responses" with `Transfer-Encoding: chunked`.
  The request timeout defaults to 300 s, max 3600 s, and returns 504 on timeout.
  https://docs.cloud.google.com/run/docs/triggering/https-request ,
  https://docs.cloud.google.com/run/docs/configuring/request-timeout [verified]. SSE responses
  are not buffered by Cloud Run [prior, widely used]. Whether IAP's front end buffers SSE is
  **not documented** [unverified]; test with `curl -N`.
- **One service, not two.** Statically export Next.js (`output: "export"`) and serve `out/`
  from the same FastAPI container (`StaticFiles`) as the AG-UI endpoint. This gives:
  - same origin, so the IAP cookie covers both and there is no CORS;
  - one cold start;
  - one IAP policy.

  This rules out Server Actions and the CopilotKit Node runtime, which fits the plain client.
  https://nextjs.org/docs/app/guides/progressive-web-apps ("Static Exports … move from Server
  Actions to calling an external API") [verified].
- **Firebase Hosting is not a fit with IAP.** Hosting→Cloud Run rewrites expect the service to
  allow unauthenticated invocations (https://firebase.google.com/docs/hosting/cloud-run
  [verified]). Hosting's streaming and timeout behaviour for SSE is not documented [unverified].
  It would also split the origin.
- **Scale to zero / cold start.** `min-instances=0`. A Python ADK + Vertex client container
  typically cold-starts in roughly 3–10 s [prior]. Use startup CPU boost. One user tolerates it.
  `min-instances=1` would cost several dollars a month and break the $1 budget [prior].
- **Cost (one user, ~tens of chats/day).**
  - Cloud Run request-based billing stays inside the free tier (180k vCPU-s, 360k GiB-s, 2M
    requests/month) [prior; the pricing page fetch was truncated].
  - IAP costs $0.
  - Artifact Registry is about $0–0.10. Keep 1–2 images; 0.5 GB is free [prior].
  - The real cost is Gemini 3.5 Flash-Lite tokens on Vertex, which is already in the existing
    budget.
  - Hosting total: about **$0–0.20/month**.

## 5. PWA on Next.js

- Manifest: use `app/manifest.ts` (`MetadataRoute.Manifest`, `display: "standalone"`, 192 and
  512 icons). Installable over HTTPS with a valid manifest. On iOS: Share → Add to Home Screen.
  https://nextjs.org/docs/app/guides/progressive-web-apps (updated 2026-07-30) [verified]
- Service worker options:
  - a hand-written `public/sw.js`, simplest with static export;
  - Serwist (`@serwist/next` 9.5.13, 2026-10-04, MIT), the maintained next-pwa successor. It is
    oriented to App Router builds; with static export, write the worker by hand or precache via
    `additionalPrecacheEntries`. https://github.com/serwist/serwist/discussions/140 [secondary]
- **IAP gotchas:**
  1. IAP returns **401 to AJAX/fetch** when the session is gone; a navigation gets a 302 to
     Google sign-in. Send `X-Requested-With: XMLHttpRequest` on fetches. On 401, open
     `/?gcp-iap-mode=DO_SESSION_REFRESH` in a window, or just reload.
     https://docs.cloud.google.com/iap/docs/sessions-howto [verified]
  2. The IAP session follows the Google login session; it is not a short JWT `exp` [verified].
  3. The manifest is fetched **without credentials** by default. Behind IAP it gets redirected
     and install fails silently. Use `<link rel="manifest" crossorigin="use-credentials">`
     [prior; the MDN page fetched did not show it].
  4. The service worker must not cache-first the AG-UI endpoint or any IAP redirect. Cache the
     static shell only, and send navigations to the network first so IAP can redirect.
  5. iOS standalone PWAs keep their own cookie jar, so the owner signs in once inside the
     installed app. The Google sign-in redirect may bounce to Safari [prior; unverified].
  6. No offline answers. Offline is a shell only.

## 6. Official Google samples

No single official Google sample combines ADK + AG-UI + Cloud Run [secondary search].
- The closest is the ADK docs CopilotKit page (https://adk.dev/integrations/copilotkit/), which
  is local-only and uses an `LlmAgent`, not a `Workflow`.
- AG-UI's `examples/server/api/human_in_the_loop.py` in the middleware repo.
- The Cloud Run "deploy ADK agents" guide (https://docs.cloud.google.com/run/docs/ai/build-and-deploy-ai-agents/adk).
- `agent-starter-pack` (now `google/agents-cli`) covers the Cloud Run deploy, not an AG-UI
  front end [secondary].

---

## Recommended stack

1. **Backend:** a FastAPI app in a new `apps/web_api` (or a `health_agents.web` module), with:
   - `App(name=APP_NAME, root_agent=build_workflow(...), resumability_config=ResumabilityConfig(is_resumable=True))`;
   - `ADKAgent.from_app(app, user_id="owner", session_service=..., memory_service=HealthMemoryService())`.
     `from_app` accepts `memory_service` (signature verified). It also has
     `execution_timeout_seconds=600` and `session_timeout_seconds=1200` as defaults.
   - `add_adk_fastapi_endpoint(api, agent, path="/agent")`, where `extract_state_from_request`
     derives `user_id` from the IAP header `X-Goog-Authenticated-User-Email` and rejects anyone
     but the owner (belt and braces).
   - Pin `ag-ui-adk==0.11.0` with `google-adk==2.12.0`.
   - Start with `emit_interrupt_outcome=False` (the tool-message flow tested above). Switch to
     `True` + `resume[]` once the client handles interrupts.
2. **Frontend:** Next.js 16 App Router with `output: "export"`, served by the same FastAPI
   container. Use plain **`@ag-ui/client` 1.0.x** with a small event reducer and custom
   components:
   - a streaming message view;
   - `ReceiptChip` → a drawer showing the SQL/Python;
   - a `ConfirmSaveFact` card for `adk_request_confirmation`;
   - a `/scoreboard` page backed by a plain JSON endpoint that calls `get_scoreboard`.

   CopilotKit is the alternative if the prebuilt chat is worth it. Its supported path needs a
   Node runtime, meaning a second service or a Node process in the container, and v2 is at RC
   today. Revisit after 2.0 GA.
3. **PWA:** `app/manifest.ts` with `crossorigin="use-credentials"`, plus a hand-written
   shell-only service worker.
4. **Hosting:** one Cloud Run service with `--iap --no-allow-unauthenticated`, `min-instances=0`,
   `--timeout=600`, startup CPU boost. IAP access is granted to the owner's Google account only.
   One-time IAP/OAuth setup in the Console (no-org project). Expected cost is about $0–0.20 per
   month plus model tokens.

## Risks / unknowns

- `ag-ui-adk` admits **known failures on ADK 2.x** in CI. Run the real multi-node workflow
  (both topologies, retry loop through `verify_receipts`, `save_fact` confirmation) through the
  middleware before committing to it.
- `ResumabilityConfig` is EXPERIMENTAL in ADK 2.12. The interrupt `outcome` fields are draft in
  the AG-UI spec, and `ag-ui-adk` had breaking HITL/session changes in 0.7.1–0.11.0, roughly
  weekly through October. Pin exact versions.
- Persistent sessions: with in-memory sessions, a pending confirmation is lost on scale-to-zero.
  Acceptable for one user; otherwise use `DatabaseSessionService` (SQLite on a GCS volume, or
  Firestore). Not evaluated here.
- Not verified:
  - whether IAP buffers SSE;
  - the IAP pricing "exceptions";
  - the Cloud Run free-tier numbers (from prior knowledge);
  - the manifest-credentials and iOS standalone cookie behaviour;
  - real cold-start time for this image.
- The AG-UI state snapshot exposes the whole session state (including `turn_outputs`, with
  tool outputs) to the browser. Fine for the owner, but review it before any public demo
  deployment.
