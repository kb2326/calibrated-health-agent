# 06 - Application, Data-Engineering, and Publishing Stack (late 2026)

Research date: 2026-10-20. Scope: frontend/agent UX, Python tooling, data engineering, publishing, public-data privacy, and a concrete recommendation for a solo ADK health-agent portfolio repo.

## Evidence posture labels

| Label | Meaning |
|---|---|
| **[PRIMARY]** | Read directly from the official docs, spec, or vendor announcement in this session |
| **[CORROBORATED]** | Two or more independent secondary sources agree; primary not fetched |
| **[SINGLE]** | One secondary source only. Treat as provisional |
| **[INFERENCE]** | My judgment from the evidence, not a sourced claim |

Search-tool dates are as reported by the source. Where a page had no visible date, it is marked "n.d. (2026 footer)".

---

## TL;DR

1. **Agent UX in late 2026 has standardized on protocols.** Hand-rolled chat boxes look dated. AG-UI hit **1.0 on 2026-09-30**, and ADK has a first-party AG-UI bridge (`ag-ui-adk`). A Next.js + CopilotKit or assistant-ui frontend that shows **tool calls, subagent handoffs, state, and HITL approvals live** is the current "modern" look. A2UI (v0.9, pre-1.0) and MCP Apps (stable 2026-01-26) are worth one showcase each, not as the foundation.
2. **Python tooling has settled:** uv (workspaces) + ruff + pytest + pydantic v2/pydantic-settings + pre-commit, on Python 3.12/3.13. For type checking, **pyright (or Pyrefly 1.0) is the safe gate**. ty is still beta (0.0.89 on 2026-10-16), so run it as a non-blocking extra. Note that Astral (uv/ruff/ty) agreed to be acquired by OpenAI on 2026-03-19, with an open-source pledge.
3. **Data:** keep SQLite as the system of record. Add **DuckDB (ATTACH the SQLite file) + Parquet** for analytics and window functions, and **pandera** checks on the frames the agents consume. dbt/SQLMesh and Dagster/Prefect are **overkill** for this project unless the aim is specifically to show data-engineering skills. Even then, a small dbt-duckdb project is enough, and an orchestrator isn't.
4. **Publishing:** a README with a hero GIF, a Mermaid architecture diagram, an **eval scorecard table**, a live-demo link, and ADRs. Ship docs with **Zensical or Starlight, not new Material for MkDocs**, since Material for MkDocs is in maintenance mode until 2026-11-05.
5. **Privacy:** wearable signals re-identify people very easily (86-100% re-identification in a systematic review). Keep raw data private. The public demo should run on a **synthetic twin plus time-shifted, aggregate-only views**, with an IAP-gated owner mode. Cloud Run IAP needs no load balancer as of 2026-03-13.

---

## 1. Agent UX: generative UI and agent-frontend protocols

### 1.1 The protocol layer (what's real in Oct 2026)

| Protocol | What it does | Status | Evidence |
|---|---|---|---|
| **AG-UI** (CopilotKit-originated) | Event stream between the agent backend and the frontend. Covers text deltas, tool-call start/result, state snapshot/delta, run lifecycle, interrupts | **1.0 stable, 2026-09-30.** Adds subagent events (`SUBAGENT_STARTED/FINISHED`), metadata (e.g. trace IDs), multimodal tool results, HITL interrupts, and token-usage reporting. JSON-Schema spec with generated TS/Python/.NET SDKs, backward compatible with 0.x. Adopters claimed: Google, Microsoft, Amazon, Oracle, LangChain, Mastra, Claude Managed Agents | [PRIMARY] https://www.copilotkit.ai/blog/ag-ui-1.0 (2026-09-30) |
| **ADK and AG-UI** | ADK's official integration page. Python/TS/Go/Java supported, with CopilotKit plus community Kotlin/Java/Go clients. Covers chat, generative UI for tools, and two-way shared state | Official | [PRIMARY] https://adk.dev/integrations/ag-ui/ (n.d., 2026 footer) |
| **ADK and CopilotKit** | Backend: `google-adk`, `ag-ui-adk`, `fastapi`, `uvicorn`. Use `AGUIToolset()`, wrap the agent in an `App` with `ResumabilityConfig(is_resumable=True)`, then `ADKAgent.from_app(...)` and `add_adk_fastapi_endpoint` at `/ag-ui`. Frontend: Next.js route `app/api/copilotkit/[[...slug]]/route.ts` with `CopilotRuntime` + `HttpAgent`, plus hooks `useRenderTool`, `useComponent`, `useHumanInTheLoop`, `useAgentContext`, `useFrontendTool` | Official docs. Python 3.10-3.14 | [PRIMARY] https://adk.dev/integrations/copilotkit/ (n.d., 2026 footer). Walkthrough: https://atamel.dev/posts/2026/03-23_agui_with_adk/ (2026-03-23) |
| **A2UI** (Google) | Declarative UI intent. The agent emits JSON against a client-owned component catalog, rendered natively (React, Angular, Flutter, Lit) | **v0.9, 2026-04-17.** Pre-1.0. The roadmap lists ADK integration as "In Progress". Runs over AG-UI via middleware ("AG-UI carries the interaction, A2UI defines what the user interacts with"). A Python agent SDK (`a2ui-agent-sdk`) exists | [PRIMARY] https://developers.googleblog.com/a2ui-v0-9-generative-ui/ (2026-04-17). [CORROBORATED] roadmap https://a2ui.org/roadmap/. Codelab https://codelabs.developers.google.com/next26/adk-a2ui (Next '26) |
| **MCP Apps** (SEP-1865, `io.modelcontextprotocol/ui`) | MCP tools declare `ui://` HTML resources, which the host renders in a sandboxed iframe that talks JSON-RPC to the host | **Stable spec 2026-01-26.** The first official MCP extension. Hosts reportedly include Claude, ChatGPT, VS Code, Goose, and Postman | [PRIMARY spec] https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx. [CORROBORATED] host list https://www.ayautomate.com/blog/mcp-apps, https://composio.dev/content/what-are-mcp-apps |
| **Vercel AI SDK 6 UI message stream** | `useChat` renders `message.parts` (text, reasoning, `tool-<name>` with states incl. `approval-requested`, `source-url`, `data-*`). Custom (e.g. Python) backends emit SSE with the header `x-vercel-ai-ui-message-stream: v1` | AI SDK 6 shipped around Dec 2025 (`ToolLoopAgent`, `createAgentUIStreamResponse`). Protocol docs are current | [PRIMARY] https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol (n.d.), https://vercel.com/blog/ai-sdk-6 (~Dec 2025), https://ai-sdk.dev/docs/ai-sdk-ui/chatbot-tool-usage |

**Implication [INFERENCE]:** for an ADK backend, **AG-UI is the native path**. The bridge already exists, and it carries ADK's multi-agent and subagent structure, which is the thing this project should show off. With the AI SDK you would write your own ADK-event to UI-message-stream adapter in Python. That's doable (the protocol is simple SSE), but it's extra code that doesn't differentiate you.

### 1.2 Frontend component options

| Option | Fit for ADK | Notes | Evidence |
|---|---|---|---|
| **CopilotKit** (React/Angular/Vue) | Native via AG-UI | One vendor covers protocol, runtime, and components. `CopilotChat` handles streaming, tool display, and suggestions. Strongest HITL and shared-state story. Also ships an A2UI starter (`npx copilotkit@latest create my-app --framework a2ui`) | [PRIMARY] adk.dev/integrations/copilotkit. [CORROBORATED] https://cadenya.com/other-content/copilotkit-vs-assistant-ui-vs-ag-ui |
| **assistant-ui** | `@assistant-ui/react-google-adk` (0.0.28, ~2026-10-13) and `@assistant-ui/react-ag-ui` (0.0.63) | Composable shadcn-style primitives, so you get more design control. The ADK adapter handles streaming, tool calls, multi-agent, tool confirmations, and session state, and the docs say it works with Python ADK. Core `@assistant-ui/react` 0.15.x. Still pre-1.0 | [PRIMARY-ish, npm] https://www.npmjs.com/package/@assistant-ui/react-google-adk, https://www.assistant-ui.com/docs/runtimes/google-adk/overview |
| **AI SDK 6 + AI Elements** | Needs a custom Python adapter | Best-known React chat stack. Typed tool parts. No native ADK support | [PRIMARY] ai-sdk.dev |
| **adk web** (Angular dev UI) | Built-in | **Docs: "not meant for use in production deployments"**, so use it for dev and debugging only. Fine to *mention* as your eval/debug tool | [PRIMARY] https://adk.dev/runtime/web-interface/ (via search snippet) |
| **Next.js 16** | n/a | Released 2025-10-21. Turbopack is the default bundler, plus Cache Components (`"use cache"`), `proxy.ts` replacing middleware, React 19.2, and a DevTools MCP. 16.x is the current line | [PRIMARY] https://nextjs.org/blog/next-16. [CORROBORATED] https://www.infoq.com/news/2025/12/nextjs-16-release |

### 1.3 Lighter Python-only options and how they read

| Framework | 2026 state | Reviewer perception [INFERENCE unless cited] |
|---|---|---|
| **Gradio 6** | Svelte 5 frontend. Chatbot shows reasoning and tool calls. MCP server mode. Deploys free on HF Spaces | Reads as "ML demo". Fine, but common. [CORROBORATED] https://alternativeto.net/news/2025/11/gradio-6-released-with-faster-performance-for-creating-machine-learning-apps-in-python |
| **Streamlit** | Snowflake-backed, ubiquitous for dashboards | Reads as "data-science prototype". Weak for streaming agent traces. [CORROBORATED] https://pynions.com/streamlit-vs-gradio |
| **Mesop** (Google) | Thin coverage in 2026, low momentum | Obscure. No signal benefit. [SINGLE] |
| **Reflex / FastHTML** | Full-stack Python | Better than Streamlit for "real app" feel, but no agent-protocol ecosystem |

Career sources agree that **any live demo beats notebooks** ([CORROBORATED] https://www.dataexpert.io/blog/ultimate-guide-ai-engineering-portfolios, https://letsdatascience.com/blog/the-ml-portfolio-that-actually-gets-you-hired-in-2026). The **differentiator in late 2026 is visible agent internals**: streamed tool calls, which subagent is active, citations back to the SQL rows used, and approval gates. That's much easier to make look good in a React + AG-UI stack. [INFERENCE]

### 1.4 Modern vs dated (late 2026) [INFERENCE, informed by the above]

- **Modern:** protocol-based streaming (AG-UI or the AI SDK UI stream). Tool-call cards with input, output, and timing. A subagent timeline. Inline charts rendered as generative UI (the agent returns structured data and the client renders a typed chart component). HITL approve/deny. Citations linking to the query and rows. A trace link (Cloud Trace / Phoenix). Token/cost/latency footer (AG-UI 1.0 now carries token usage).
- **Dated:** a plain chat box with a single text blob. A "thinking..." spinner with no trace. A Streamlit `st.chat_message` loop as the *only* UI. Polling instead of streaming. Next.js 13/14 pages router. The `portfolio_stack.md` target of "Next.js 14" should be **Next.js 16**.

---

## 2. Python project tooling (Oct 2026)

| Concern | Recommendation | Status / evidence |
|---|---|---|
| Package/env manager | **uv** with a **workspace** (one root `uv.lock`, root `.venv`, `uv sync --all-packages`, apps marked `package = false`, `{ workspace = true }` sources) | [CORROBORATED] https://pydevtools.com/handbook/how-to/how-to-set-up-a-python-monorepo-with-uv-workspaces/, https://github.com/carderne/postmodern-mono. Governance note: OpenAI agreed to acquire Astral on 2026-03-19 and pledged uv/ruff/ty stay OSS [CORROBORATED] https://thenewstack.io/openai-astral-acquisition/, https://pydevtools.com/blog/openai-acquires-astral.md |
| Lint/format | **ruff** (already in the repo). Add `ruff format`, plus rule sets `S` (bandit), `SIM`, `PT`, `RUF`, `ANN` progressively | Standard |
| Type checking | **pyright** in CI as the gate, or **Pyrefly 1.0** (Meta, ~96% conformance per the Jul 2026 pydevtools figures). Run **ty** as a non-blocking job. It has been beta since Dec 2025, latest **0.0.89 (2026-10-16)**, Pydantic support since 0.0.57 (Jul 2026), and stable 1.0 is "targeted 2026" but not shipped | [PRIMARY] https://pypi.org/project/ty/. [SINGLE] conformance numbers https://pydevtools.com/handbook/explanation/ty-vs-pyrefly/. Pyrefly 1.0 https://www.infoworld.com/article/4179383/pyrefly-1-0-a-fast-forward-looking-python-linter.html |
| Models/config | **pydantic v2** for tool I/O schemas and API payloads. **pydantic-settings** for env/secret config (replacing ad-hoc YAML reads) | Standard |
| CLI | **Typer** to replace the `scripts/*.py` argparse entry points with one `health` CLI (`health sync`, `health learn`, `health digest`) | Standard [INFERENCE] |
| Tests | pytest + pytest-cov. Add **syrupy** snapshots for digest output, and **hypothesis** for SQL/analysis invariants | Standard |
| Logging | **structlog** (JSON in prod, pretty locally), correlated with **OpenTelemetry** trace IDs, which ADK can export to Cloud Trace. AG-UI 1.0 metadata can carry the trace ID to the UI | [INFERENCE]. AG-UI metadata [PRIMARY] above |
| Hooks | **pre-commit** (or the faster Rust drop-in `prek`) running ruff, pyright, gitleaks, and a "no real data" guard (block `*.db`, `*.parquet` outside `data/synthetic/`) | [INFERENCE] |
| Python version | **3.12 or 3.13** (ADK supports 3.10-3.14 per the CopilotKit/ADK page). The repo currently pins `>=3.11` / `py311`. Bump to 3.12 | [PRIMARY] adk.dev/integrations/copilotkit |
| Docker | Multi-stage build on the official `ghcr.io/astral-sh/uv` image. First copy `pyproject.toml` + `uv.lock` + member manifests and `uv sync --frozen --no-install-workspace --package api`, then copy the source and sync again. Non-root user, `python:3.13-slim` runtime, no data baked in | [CORROBORATED] uv issue #6935 https://github.com/astral-sh/uv/issues/6935, https://gafni.dev/blog/cracking-the-python-monorepo/. Official guide: docs.astral.sh/uv/guides/integration/docker (not re-fetched) |
| Devcontainer | `.devcontainer/devcontainer.json` (Python + Node features, uv preinstalled, seeded with synthetic data) so **Codespaces works in one click**. That's a strong reviewer affordance for very little effort | [INFERENCE] |

---

## 3. Data engineering for personal time series

### 3.1 Engines

| Tool | Role here | Evidence |
|---|---|---|
| **SQLite** (current, ~480 MB) | Keep as the **OLTP/system of record** for sync, journal, and learned facts. It's right-sized | [INFERENCE] |
| **DuckDB** (stable v1.5.x, ~1.5.6 on 2026-09-28 per Wikipedia) | Analytics engine. `ATTACH 'health.db' (TYPE sqlite)` reads the SQLite file in place (read/write supported), so there's no migration. Strong window functions for rolling baselines, lags, and anomaly z-scores. `COPY ... TO 'x.parquet'` for the public/synthetic exports | [PRIMARY] https://duckdb.org/docs/lts/core_extensions/sqlite. [SINGLE] version https://en.wikipedia.org/wiki/DuckDB |
| **Polars** | Optional. Only worth it if you want to show it. Benchmarks show wins mainly above ~1 GB | [CORROBORATED] https://www.danilchenko.dev/posts/duckdb-vs-polars/, https://uvik.net/blog/polars-vs-pandas/ |
| **pandas 3.0** | Fine for the existing scripts (copy-on-write, Arrow strings by default, `pd.col()`). Don't rewrite for its own sake | [CORROBORATED] https://www.birjob.com/blog/polars-duckdb-pandas-2026-decision-guide |
| **Parquet** | Format for the synthetic twin and public aggregates. Columnar and diffable via DuckDB. Can be shipped in GitHub Releases | [INFERENCE] |

**Recommendation [INFERENCE]:** run "SQLite, attached by DuckDB, exported to Parquet". The agents' `run_sql` tool should target **DuckDB over the attached SQLite (read-only)**. That gives SQL window functions for the Data-Scientist agent, and it's an easy story to tell in an ADR.

### 3.2 Transformations

- **dbt**: Fivetran and dbt Labs completed their merger on 2026-06-01, and dbt's Rust engine (Fusion / "v2") is reportedly GA in Sep 2026 [SINGLE] https://pythondatabench.com/article/sqlmesh-vs-dbt-2026. dbt is still the default most teams pick [CORROBORATED] https://synq.io/blog/dbt-vs-sqlmesh-a-comparison-for-modern-data-teams.
- **SQLMesh**: Fivetran acquired Tobiko (Sep 2025), and SQLMesh was donated to the Linux Foundation (2026-03-25) [SINGLE] same source. It has better virtual environments, but its benefits show at scale.
- **Verdict [INFERENCE]:** for ~10-20 derived tables (daily rollups, baselines, sleep sessions), plain **versioned SQL views in DuckDB** plus tests are enough. If you want the data-engineering resume line, a **small `dbt-duckdb` project (staging, then marts) with dbt tests** is the most recognizable choice. Skip SQLMesh, since recruiters won't recognize it as much.

### 3.3 Data quality

- **pandera** (0.32 docs, native Polars plus an opt-in Narwhals backend). Write `DataFrameModel` schemas for the frames the agents read, with range checks (HR 25-230, sleep minutes 0-1440), monotonic timestamps, and no duplicate days [PRIMARY] https://pandera.readthedocs.io/en/latest/polars.html.
- **dbt tests** if using dbt. **Great Expectations** is heavy for a solo project, so it's overkill [INFERENCE].
- Running these checks in CI against the **synthetic twin** gives a green "data contracts" badge. That's cheap and reads well [INFERENCE].

### 3.4 Orchestration

- Market context: **Prefect agreed to acquire Dagster Labs (announced ~2026-07-13)**. The products stay separate [PRIMARY-ish] https://dagster.io/dagster-customer-faq. Dagster+ Solo/Starter dropped included credits in May 2026 (vendor-sourced by Prefect) [SINGLE] https://www.prefect.io/compare/dagster.
- **Verdict [INFERENCE]:** the batch loops (sync, learn, digest) run daily. **Cloud Scheduler + Cloud Run Jobs** (or a GitHub Actions cron for the synthetic pipeline) is the right size. Dagster's asset lineage UI looks great, but it means running another service and learning another mental model for about 4 jobs. Count it as **trendy-but-overkill**. If you want lineage visuals, render a Mermaid DAG in the README.

---

## 4. Publishing and presentation

### 4.1 README anatomy (2026 consensus) [CORROBORATED: dataexpert.io, letsdatascience.com, https://github.com/matiassingers/awesome-readme]

1. One-line value prop, plus a **hero GIF or 60-90 s video** (agent streaming tool calls on the synthetic twin).
2. Badges: CI, coverage, type-check, eval score, license, Python version, "Open in Codespaces", "Live demo".
3. **Mermaid architecture diagram** (GitHub renders it natively). Also a sequence diagram of one query through the subagents.
4. **Eval scorecard table**: named metrics, numbers, targets, p50/p95 latency, cost per query. Reviewers scan for exactly this.
5. A "Why it's safe" section (read-only by construction, synthetic public data, IAP owner mode).
6. Quickstart in at most 3 commands (`uv sync`, `health demo`, `pnpm dev`) running on synthetic data.
7. A link to ADRs (`docs/adr/`). You already have ADR-008, so keep the numbering. Also link a blog post.

### 4.2 GitHub features worth using [INFERENCE + standard GitHub features]

- **Actions:** lint/type/test, eval run on PR (post scorecard as a PR comment), synthetic-data contract tests, Docker build + deploy to Cloud Run via Workload Identity Federation (no JSON keys).
- **Releases** with a changelog, plus the synthetic Parquet dataset attached as an asset.
- **Pages** for the docs site. **Codespaces** via devcontainer. **Repo topics** (`google-adk`, `ag-ui`, `agentic-ai`, `multi-agent`, `wearables`, `duckdb`, `health-data`). A custom **social preview image** (1280x640).
- **Pinned** on the profile. Write the README's first screen for a reviewer who gives it about 90 seconds.

### 4.3 Docs sites

- **Material for MkDocs is in maintenance mode.** The last feature release was 9.7.0 (2025-11-11), and critical fixes continue only through **2026-11-05**. The team now builds **Zensical**, which reads `mkdocs.yml` [CORROBORATED] https://github.com/squidfunk/mkdocs-material/issues/8523, https://pydevtools.com/handbook/reference/mkdocs-material/.
- **Recommendation [INFERENCE]:** for a Python-centric repo, use **Zensical** (it's Python and reuses MkDocs conventions). Pick **Astro Starlight** if the Next.js/TS side is the center of gravity. Honestly, the README plus `docs/adr/*.md` rendered by GitHub may be enough, so a docs site is **optional**.

### 4.4 Launch

- **Blog post:** your own domain or Hashnode (custom domain, canonical URL), cross-posted to dev.to. Use the title shape "What I learned building a multi-agent system over 2 years of my own wearable data". Lead with the eval numbers and a failure story [INFERENCE].
- **Show HN:** post only when the demo is live and works without login. HN responds well to personal-data, self-hosted, and privacy-first framing. Comparable posts: "Show HN: Open Wearables" https://news.ycombinator.com/item?id=47274252 (~Mar 2026), HiMe https://github.com/thinkwee/HiMe plus its arXiv paper https://arxiv.org/html/2607.21019 (Jul 2026) [PRIMARY listings].
- **Ecosystem context:** Google released an official open-source **Google Health CLI (`ghealth`, Go, Apache-2.0, ships Agent Skills)** around 2026-07-02 [CORROBORATED] https://www.marktechpost.com/2026/07/02/the-google-health-api-got-a-cli-ghealth-is-an-open-source-tool-for-your-fitbit-air-data/. Community MCP servers exist too (e.g. https://github.com/BerkKilicoglu/google-health-fitbit-mcp, https://github.com/mstuart/vitals). **Differentiate on multi-agent reasoning, the learning loop, and evals, not on data access.** Consider interoperating with `ghealth` (e.g. an ADR on why you kept your own read-only client).
- Note that Google Health API scopes are **Restricted** and need a privacy/security review for production access. That's another reason the public demo must not do live OAuth for strangers [CORROBORATED] same MarkTechPost source.
- **License:** Apache-2.0 matches ADK, A2UI, and ghealth, and includes a patent grant. MIT also works. Avoid noncommercial licenses (HiMe's PolyForm NC limits reuse). Put the **synthetic dataset under CC-BY-4.0** and do not license the real data at all [INFERENCE].

---

## 5. Presenting real personal data publicly without regret

**Threat reality [PRIMARY-ish]:** a Lancet Digital Health systematic review of 72 studies found **86-100% correct re-identification** from de-identified wearable data, sometimes from 1-300 s of signal https://pubmed.ncbi.nlm.nih.gov/36797124/ (2023). HR and sleep patterns reveal routines and stress periods https://arxiv.org/pdf/2503.03428. **Conclusion: removing your name doesn't de-identify the data, so never publish raw minute-level series.**

Layered approach [INFERENCE, grounded in the above]:

| Layer | What | Notes |
|---|---|---|
| 1. **Private owner mode** | Real SQLite stays in GCS/Cloud Run volume (or local only). The Cloud Run service sits behind **IAP**, enabled directly on Cloud Run with no load balancer and at no added cost (GA 2026-03-13) | [PRIMARY] https://docs.cloud.google.com/iap/docs/enabling-cloud-run, https://cloud.google.com/blog/products/serverless/iap-integration-with-cloud-run |
| 2. **Synthetic twin (public default)** | Generate daily/hourly series that match your marginals, weekly seasonality, cross-metric correlations (sleep to HRV to RHR), and inject labeled anomalies (illness week, travel). Simple and explainable beats fancy: a seasonal decomposition + AR residuals + Gaussian copula across metrics, done in numpy/statsmodels. That's about 200 lines, and you can **test fidelity** (KS tests, correlation-matrix diff, discriminator AUC near 0.5) | SDV moved to the **Business Source License** (not OSI), so avoid it as a dependency in an Apache repo [CORROBORATED] https://devtoollab.com/blog/best-synthetic-data-generation-tools. The research field is moving to diffusion models, but formal user-level privacy is still open [PRIMARY] https://academic.oup.com/jamiaopen/article/9/2/ooag066/8660461 (2026) |
| 3. **Time-shift + jitter** | If any real-derived artifacts are shown (e.g. screenshots), shift all dates by a secret random offset, round to day level, and drop timezone/location | Standard clinical de-id practice [INFERENCE] |
| 4. **Aggregate-only public views** | Weekly or monthly means, ranges, correlation coefficients. No raw daily rows. Optionally add Laplace noise to published aggregates | [INFERENCE]. DP note from JAMIA Open 2026: record-level DP is not user-level, and for a single user everything is user-level |
| 5. **Guardrails in code** | A `DATA_MODE=synthetic|owner` setting (pydantic-settings). The public deployment physically has no real DB mounted. Pre-commit/CI block committing `*.db` and real Parquet, and gitleaks covers OAuth tokens. The demo agent's prompts cannot reach the owner store | [INFERENCE] |
| 6. **Write it up** | An ADR "Public demo uses a synthetic twin". The fidelity report in the README is itself a portfolio signal | [INFERENCE] |

---

## 6. Recommended stack and repo layout

### 6.1 Recommendation table

| Layer | Pick | Why | Trendy-but-overkill (skip) |
|---|---|---|---|
| Agent runtime | **Google ADK (Python)**, existing | Already built. Has an official AG-UI bridge | Rewriting to LangGraph (as `portfolio_stack.md` suggested). ADK now has first-class UI-protocol support, so a switch would lose the work done so far |
| Agent to UI protocol | **AG-UI 1.0** via `ag-ui-adk` | Native to ADK, just went 1.0, carries subagent events, HITL, token usage | Writing a custom SSE protocol. Building on A2UI as the core (it's v0.9) |
| Frontend | **Next.js 16 + CopilotKit** (fastest), or **assistant-ui** (more custom look), with shadcn/ui, Tailwind v4, Recharts/visx for generative chart components | The modern, recognizable agent UX | Building your own chat primitives. Vercel AI SDK *plus* an ADK adapter you'd have to write |
| Generative UI showcase | 1-2 typed tool renderers (sleep chart, anomaly card) via `useRenderTool`. **One** A2UI demo component | Shows generative UI without depending on pre-1.0 specs | A full A2UI catalog |
| MCP | Expose read-only tools as an MCP server (FastMCP). Optional **MCP Apps** chart widget for Claude/ChatGPT hosts | MCP Apps is stable and supported by major hosts, so you get a cheap "works inside Claude" demo | Supporting every host |
| Backend API | FastAPI (from `ag-ui-adk`) on **Cloud Run** | Scale-to-zero, cheap | GKE. Agent Engine *only* if you want the managed-runtime line (deploys take 5-10 minutes) |
| Auth | **Cloud Run direct IAP** for owner mode. The public demo is unauthenticated with synthetic data, rate-limited, with a budget cap | Zero load balancer, zero code | Building user accounts or OAuth for visitors |
| Batch | **Cloud Run Jobs + Cloud Scheduler**. Locally: the `health` Typer CLI | Right-sized for ~4 daily jobs | Dagster, Prefect, Airflow |
| Storage | **SQLite (system of record) + DuckDB (analytics, attached) + Parquet (synthetic/public)** | No migration. Good window functions | Postgres/AlloyDB, BigQuery for 480 MB, a vector DB for structured metrics |
| Transforms | Versioned DuckDB SQL views. Optional `dbt-duckdb` if you want the DE signal | Small DAG | SQLMesh. dbt Cloud |
| Data quality | **pandera** schemas + CI on synthetic | Light. Badge-able | Great Expectations |
| Python tooling | **uv workspace, ruff, pyright (gate) + ty (advisory), pytest, pydantic v2, pydantic-settings, Typer, structlog, pre-commit**, Python 3.13 | The 2026 default | Making ty the blocking gate (still beta). Poetry/pip-tools |
| Observability | OpenTelemetry to Cloud Trace, with trace ID surfaced in UI via AG-UI metadata | Visible "production thinking" | Running a self-hosted LangFuse/Phoenix server unless evals need it |
| CI/CD | GitHub Actions: lint/type/test, eval scorecard comment, Docker build, deploy via Workload Identity Federation | Standard | Multiple environments, Terraform for everything (a small `infra/` with gcloud scripts or minimal Terraform is fine) |
| Docs | README + ADRs. Optional **Zensical** site on Pages | Material for MkDocs is in maintenance mode | Full Docusaurus/Starlight site with versioning |
| Dev env | devcontainer + Codespaces badge, seeded with synthetic data | One-click try | Nix |
| License | Apache-2.0 (code), CC-BY-4.0 (synthetic data) | Matches the ecosystem | Noncommercial licenses |

### 6.2 Repo layout (uv + pnpm workspaces)

```
google-health-agent/
├─ apps/
│  ├─ api/                 # FastAPI + ag-ui-adk endpoint (package=false), Dockerfile
│  ├─ web/                 # Next.js 16 + CopilotKit/assistant-ui, generative UI components
│  └─ jobs/                # Typer CLI: sync | learn | digest | synth (Cloud Run Jobs entrypoint)
├─ packages/
│  ├─ health_core/         # read-only Google Health client, settings (pydantic-settings), models
│  ├─ health_data/         # SQLite + DuckDB access, SQL views, pandera schemas
│  ├─ health_agents/       # ADK agents/tools/callbacks (orchestrator + subagents)
│  ├─ health_synth/        # synthetic twin generator + fidelity tests
│  └─ health_mcp/          # optional FastMCP server (+ MCP Apps widget)
├─ evals/                  # ADK evalsets, scorecard generator
├─ data/
│  ├─ synthetic/           # committed or Release-attached Parquet (CC-BY-4.0)
│  └─ .gitignore           # real *.db never committed
├─ docs/
│  ├─ adr/                 # ADR-001..00N (keep existing numbering)
│  └─ assets/              # hero.gif, architecture.svg, social-preview.png
├─ infra/                  # gcloud/Terraform: Cloud Run svc + jobs, Scheduler, IAP, WIF
├─ .devcontainer/
├─ .github/workflows/      # ci.yml, evals.yml, deploy.yml
├─ pyproject.toml          # [tool.uv.workspace] members = ["apps/*", "packages/*"]
├─ uv.lock
├─ pnpm-workspace.yaml
└─ README.md
```

Migration note [INFERENCE]: the current `scripts/*.py` map onto `packages/health_core` (client, auth, db) and `apps/jobs` (sync, learn, digest, journal), and `health_agent/` maps onto `packages/health_agents`. Do it in one mechanical PR with tests green, before adding the frontend.

### 6.3 Explicit "trendy but overkill for a solo project" list

- Dagster/Prefect/Airflow for 4 daily jobs. SQLMesh. Great Expectations. dbt Cloud.
- Polars rewrite of working pandas code (only worth it as a deliberate learning exercise).
- Vector DB / RAG over structured numeric metrics. SQL is the right retrieval layer here.
- Building the core UI on A2UI (v0.9) or a full MCP Apps suite. Do one showcase each.
- GKE, multi-env Terraform, service mesh. Full auth/accounts for visitors.
- ty as the only blocking type checker (still beta). Nix devshells.
- Kafka/streaming ingestion. The data source is a daily batch API.

### 6.4 Learning-value picks (trending skills worth the effort) [INFERENCE]

AG-UI protocol and generative UI, Next.js 16 server/client boundaries, uv workspaces, DuckDB SQL window analytics, pandera data contracts, synthetic data with fidelity testing, Cloud Run direct IAP + Workload Identity Federation, OpenTelemetry tracing end to end, MCP server + MCP Apps.

---

## Source list (consolidated)

- AG-UI 1.0 - https://www.copilotkit.ai/blog/ag-ui-1.0 (2026-09-30)
- ADK AG-UI - https://adk.dev/integrations/ag-ui/ (n.d., 2026)
- ADK CopilotKit - https://adk.dev/integrations/copilotkit/ (n.d., 2026)
- AG-UI with ADK walkthrough - https://atamel.dev/posts/2026/03-23_agui_with_adk/ (2026-03-23)
- A2UI v0.9 - https://developers.googleblog.com/a2ui-v0-9-generative-ui/ (2026-04-17); roadmap https://a2ui.org/roadmap/; codelab https://codelabs.developers.google.com/next26/adk-a2ui
- MCP Apps spec - https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx (2026-01-26)
- AI SDK stream protocol - https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol; AI SDK 6 - https://vercel.com/blog/ai-sdk-6
- assistant-ui ADK - https://www.npmjs.com/package/@assistant-ui/react-google-adk (~2026-10); https://www.assistant-ui.com/docs/runtimes/google-adk/overview
- CopilotKit vs assistant-ui vs AG-UI - https://cadenya.com/other-content/copilotkit-vs-assistant-ui-vs-ag-ui (2026)
- ADK web UI - https://adk.dev/runtime/web-interface/
- Next.js 16 - https://nextjs.org/blog/next-16 (2025-10-21)
- Gradio 6 - https://alternativeto.net/news/2025/11/gradio-6-released-with-faster-performance-for-creating-machine-learning-apps-in-python (2025-11)
- ty on PyPI - https://pypi.org/project/ty/ (0.0.89, 2026-10-16); ty vs Pyrefly - https://pydevtools.com/handbook/explanation/ty-vs-pyrefly/ (2026)
- OpenAI and Astral - https://thenewstack.io/openai-astral-acquisition/ (2026-03); https://pydevtools.com/blog/openai-acquires-astral.md
- uv workspaces - https://pydevtools.com/handbook/how-to/how-to-set-up-a-python-monorepo-with-uv-workspaces/; https://github.com/astral-sh/uv/issues/6935; https://gafni.dev/blog/cracking-the-python-monorepo/
- DuckDB SQLite extension - https://duckdb.org/docs/lts/core_extensions/sqlite
- DuckDB vs Polars - https://www.danilchenko.dev/posts/duckdb-vs-polars/ (2026)
- dbt vs SQLMesh - https://pythondatabench.com/article/sqlmesh-vs-dbt-2026; https://synq.io/blog/dbt-vs-sqlmesh-a-comparison-for-modern-data-teams
- Prefect acquires Dagster - https://dagster.io/dagster-customer-faq (2026-07)
- pandera + Polars - https://pandera.readthedocs.io/en/latest/polars.html
- Material for MkDocs maintenance - https://github.com/squidfunk/mkdocs-material/issues/8523; https://pydevtools.com/handbook/reference/mkdocs-material/
- Cloud Run direct IAP - https://docs.cloud.google.com/iap/docs/enabling-cloud-run; https://cloud.google.com/blog/products/serverless/iap-integration-with-cloud-run (GA 2026-03-13)
- Wearable re-identification review - https://pubmed.ncbi.nlm.nih.gov/36797124/
- DP synthetic behavioral health (2026) - https://academic.oup.com/jamiaopen/article/9/2/ooag066/8660461
- SDV license - https://devtoollab.com/blog/best-synthetic-data-generation-tools (2026)
- Google Health CLI - https://www.marktechpost.com/2026/07/02/the-google-health-api-got-a-cli-ghealth-is-an-open-source-tool-for-your-fitbit-air-data/ (2026-07-02)
- Comparable projects - https://news.ycombinator.com/item?id=47274252; https://github.com/thinkwee/HiMe; https://arxiv.org/html/2607.21019; https://github.com/mstuart/vitals
- Portfolio signals - https://www.dataexpert.io/blog/ultimate-guide-ai-engineering-portfolios; https://letsdatascience.com/blog/the-ml-portfolio-that-actually-gets-you-hired-in-2026; https://github.com/matiassingers/awesome-readme
