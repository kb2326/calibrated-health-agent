# 02 — Multi-agent frameworks, orchestration, protocols & memory (state of the art, 20 Oct 2026)

Scope: what a solo engineer should build a multi-agent personal-health system on in late 2026, given the existing Google ADK codebase (`health_agent/agent.py`, `google-adk` **2.7.1** installed, orchestrator + `data_scientist` / `domain_expert` / `health_coach` via `sub_agents`), a 480 MB SQLite substrate, a prediction-scoring learning loop, and GCP access.

Builds on `research_notes/Health agent portfolio revamp/agentic architecture standards.md` and `agent protocols MCP A2A.md` (19 Oct 2026). Where this file contradicts or updates them, it says so.

**Evidence labels:** **[primary]** = official docs, release notes, PyPI/GitHub/npm registries queried directly today · **[benchmark]** = paper or reproducible eval · **[vendor]** = vendor blog/marketing or vendor-run benchmark · **[secondary]** = third-party blog or aggregator · **[anecdote]** = forum post or single practitioner.

---

## Executive summary

1. **Keep ADK, upgrade it, and fix how delegation works.** ADK Python is shipping roughly every two weeks (2.12.0 on 13 Oct 2026), has about 10M PyPI downloads a month, and now has a graph `Workflow` runtime, HITL confirmation, resume, `abort_signal`, a SQLite memory service, MCP SDK 2.x, and native A2A task mode. Switching to LangGraph would cost weeks and show the same skill a reviewer already sees. The bigger issue is a **correctness bug in the current design**: the default `sub_agents` mode in ADK 2.x is `chat`. In that mode the orchestrator *hands the conversation off* to a specialist and does not get control back automatically. So the root instruction "delegate data_scientist then domain_expert and synthesise one answer" can't happen as written. Use `mode="single_turn"` (or `task`), or a graph `Workflow`. [primary]
2. **LangGraph still leads on demand and mindshare** (about 44.8M downloads a month, 43.6K stars, 1.2.16 on 16 Oct 2026). It's the safest keyword. But a well-engineered ADK system plus a framework-agnostic eval harness, and one small LangGraph artifact if you want the keyword, beats a rewrite. [primary + secondary]
3. **Orchestration best practice has converged on a few rules.** Use a deterministic workflow for the known path and LLM steps only where judgment is needed. Use centralised orchestration rather than independent swarms. Don't use multi-agent setups for sequential reasoning. Durable execution and HITL are table stakes. Google/MIT's scaling study found every multi-agent variant **degraded sequential reasoning by 39–70%**, and independent agents amplified errors 17.2x against 4.4x for centralised ones. [benchmark]
4. **Protocols, ranked by how justified they are for this project.** **MCP** (spec 2026-07-28, stateless, SDK v2.3.0) is justified and expected. **A2A** v1.0 is real but only earns its place when there's a genuine cross-framework boundary, which you'd have to create on purpose. **AG-UI 1.0** (30 Sep 2026) is the right choice if you build a web UI. **A2UI** is pre-1.0. **AP2** was donated to FIDO (Apr 2026), its GitHub repo has been dormant since April, and it isn't relevant here. [primary + secondary]
5. **Memory.** Vendor leaderboard numbers (Mem0, Zep, Letta on LoCoMo/LongMemEval) are disputed and mostly self-reported. Independent work (MemoryAgentBench, ICLR 2026; EvoMemBench) finds long-context baselines "highly competitive". For one user, the right move is a **typed, bi-temporal memory you own in SQLite**, exposed through ADK's `BaseMemoryService`. Vertex/Agent Platform Memory Bank is optional as a managed comparison arm. LangMem is effectively in maintenance (last PyPI release Oct 2025). [primary + benchmark]
6. **Code execution is the highest-leverage capability gap.** PHIA (Nature Communications, accepted) reached 84% on objective wearable questions with a code-plus-retrieval agent. Google's own Personal Health Agent, which this repo copies, gives its Data Science agent code generation. The current repo has only fixed SQL tools and `run_sql`. Add a sandboxed Python executor: GKE/Agent Platform sandbox, a `ContainerCodeExecutor` locally, or E2B. [benchmark + primary]

---

## 1. Frameworks: versions, momentum, adopters

### 1.1 Verified registry snapshot (queried 2026-10-20) [primary]

| Framework | Latest version (date) | PyPI/npm downloads, last month | GitHub stars | Cadence / notes |
|---|---|---|---|---|
| **LangGraph** (Py) | 1.2.16 (2026-10-16) | **44.8M** | 43.6K | 1.0 on 2025-10-17; 1.1 on 2026-03-10; 1.2 on 2026-05-12; patch releases every 1–2 weeks. [PyPI](https://pypi.org/project/langgraph/) |
| **Google ADK** (Py) | 2.12.0 (2026-10-13) | **10.1M** | 21.9K (Py), Go 8.9K, Java 1.75K, JS 1.44K | 2.0 GA 2026-05-19; about bi-weekly minors; 1.x maintained in parallel until 1.39.1 (Aug 2026). [PyPI](https://pypi.org/project/google-adk/), [releases](https://github.com/google/adk-python/releases) |
| ADK TS (`@google/adk`) | 2.3.0 | — | 1.44K | TS 2.0 GA reported 2026-08-21; Go 2.0 2026-06-30. [secondary: DEV](https://dev.to/peytongreen_dev/google-adk-20-is-now-stable-workflow-runtimes-breaking-changes-and-how-to-migrate-4ah8) |
| **OpenAI Agents SDK** (Py) | 0.24.0 (2026-10-15) | n/a (pypistats 502) | 30.2K | 88 releases in 12 months, still 0.x. Sandbox agents (Apr 2026) and Temporal integration GA (Mar 2026). [PyPI](https://pypi.org/project/openai-agents/), [Temporal](https://temporal.io/blog/introducing-temporal-and-agentic-sandboxes-openai-agents-sdk) |
| **Claude Agent SDK** (Py) | 0.2.168 (2026-10-15) | **29.8M** | 8.3K | About 15–20 releases a month, many yanked. Hooks, in-process SDK MCP servers, sessions, subagents. Hosted counterpart "Managed Agents" (Apr 2026). [PyPI](https://pypi.org/project/claude-agent-sdk/), [secondary](https://hatchworks.com/blog/claude/claude-agent-sdk-and-managed-agents/) |
| **Pydantic AI** | 2.58.0 (2026-10-20) | 5.4M (`pydantic-ai`) + 23.9M (`-slim`) | 20.7K | 1.0 on 2025-09-05; 2.0 on 2026-06-23; about 60 releases since. Eight durable-execution backends (Temporal, DBOS, Prefect, Restate, …), Pydantic Graph, AG-UI. [PyPI](https://pypi.org/project/pydantic-ai/) |
| **CrewAI** | 1.15.28 (2026-10-14) | 2.4M | 59.9K | Stars high and downloads modest. Prototype-speed reputation, weakest durability in 2026 benchmarks. |
| **Microsoft Agent Framework** (Py) | 1.22.0 (2026-10-15) | 0.19M | 14.2K | 1.0 on 2026-04-02. AutoGen (61.5K stars) and Semantic Kernel are in maintenance mode. [PyPI](https://pypi.org/project/agent-framework/), [secondary](https://rywalker.com/research/autogen) |
| **Mastra** (TS) | `@mastra/core` 1.78.0 | **8.0M** (npm) | 28.9K | 1.0 in Jan 2026; $22M Series A in Apr 2026; users include Replit and Brex. [secondary](https://byteiota.com/mastra-1-0-typescript-ai-framework-reaches-production/) |
| deepagents (LangChain) | 0.7.28 | — | 30.4K | LangChain's "agent harness" layer on LangGraph, fast-rising star count. |

Caveats: Claude Agent SDK and `pydantic-ai-slim` download counts are inflated by being transitive dependencies of popular tools (Claude Code tooling, Logfire and others). Stars measure attention, not production use. I couldn't get monthly trend series because the pypistats `overall` endpoint failed, so "rising/falling" below rests on release activity, stars, and secondary reports.

### 1.2 Rising / steady / falling (judgement)

- **Rising:** Google ADK (2.0 graph runtime, four languages, Agent Platform integration, about 10M a month); Pydantic AI (fastest feature velocity, best durable-execution story); Mastra (TS default); Claude Agent SDK and OpenAI Agents SDK (harness-style "give the agent a computer" SDKs, both adding sandboxes); deepagents.
- **Steady leader:** LangGraph. It's the most downloaded and most named in job descriptions, and LangGraph Platform was renamed **LangSmith Deployment** (Oct 2025) ([LangChain changelog](https://changelog.langchain.com/announcements/product-naming-changes-langsmith-deployment-and-langsmith-studio)) [primary]. 1.2 added node timeouts and error handlers, plus `interrupt(..., response_schema=)` in 1.2.12 ([secondary: Developers Digest](https://www.developersdigest.tech/blog/langchain-langgraph-whats-new-2026)). The October 2026 releases are mostly durability and interrupt-resume fixes (DeltaChannel replay, subgraph resume, `PostgresSaver.prune` in checkpoint-postgres 3.2.0) ([releases](https://github.com/langchain-ai/langgraph/releases)) [primary].
- **Falling / legacy:** AutoGen and Semantic Kernel (maintenance only, migrate to MS Agent Framework); CrewAI relative to its stars; LangMem (see §4).
- **Survey data point:** Stack Overflow's April 2026 pulse survey (~1,100 devs) found LangChain at 22%, OpenClaw at 17%, and LangGraph at 14% adoption ([secondary citation](https://the-agent-report.com/2026/07/ai-agent-frameworks-comparison-2026-langgraph-crewai-autogen/)). No ADK figure was reported.
- **Hiring signal** (from the sibling note `portfolio hiring signals.md`): MCP and LangGraph are high-volume keywords. **Google ADK and A2A show up as "differentiators" in enterprise job descriptions** (Citi lists "Google ADK, LangGraph, CrewAI, or the OpenAI Agents SDK") but not in top-10 frequency lists.

### 1.3 ADK 2.x specifics relevant to this repo [primary unless noted]

From the [adk-python releases](https://github.com/google/adk-python/releases) and [adk.dev](https://adk.dev/workflows/):
- **2.0 (2026-05-19):** graph engine; `BaseAgent` extends `BaseNode`. Three composition styles: graph workflows (edges, route maps), dynamic workflows (`ctx.run_node` in async code), and collaborative coordinator agents. This was a breaking change to the agent API, event model, and session schema ([secondary](https://dev.to/peytongreen_dev/google-adk-20-is-now-stable-workflow-runtimes-breaking-changes-and-how-to-migrate-4ah8)).
- **2.8 (26 Aug):** native A2A task mode in `RemoteA2aAgent` plus auth; Memory Bank `memory_id` / `allowed_topics`; custom eval metrics; parallel LLM-as-judge; Model Armor plugin.
- **2.9 (10 Sep):** failed node reruns on workflow resume ("side effects must be idempotent"); YAML graphs; `FallbackModel`; A2A requires https for remote agent cards; trajectory eval `ignore_args`; MCP SDK 2.x support.
- **2.10 (25 Sep):** eval efficiency metrics (duration, tokens, model calls); Skills lifecycle (experimental); MongoDB hybrid-search toolset.
- **2.11 (2 Oct):** `abort_signal` for cancellation; tool-node HITL via `RequestInput`; **SQLite memory service (`sqlite://`)**; opt-in MCP SDK 2.x connections; `ToolCallIntegrityPlugin`.
- **2.12 (13 Oct):** `require_confirmation` pauses workflow nodes for human approval; resume of paused Gemini generations; task-mode wrappers with sub-agent delegation and resume; about 40% faster time to first model request in long sessions; `after_tool_callback` output filtering.

**Delegation semantics (important for this repo):** in ADK 2.x, declaring `sub_agents` auto-generates one delegation tool per sub-agent, and each sub-agent has a **mode** ([adk.dev collaboration](https://adk.dev/workflows/collaboration/)):
- `chat` (**default**): the sub-agent owns the conversation until something calls `transfer_to_agent` explicitly.
- `task`: the sub-agent may ask clarifying questions and returns automatically on `finish_task`. Task-mode agents must be leaves.
- `single_turn`: no user interaction, returns automatically, and can run in parallel in its own session branch.

`health_agent/agent.py` sets no mode, so it uses `chat`. The root's "delegate in that order and synthesise" instruction relies on control coming back, and `chat` mode doesn't give it back automatically. **Set `mode="single_turn"` on `data_scientist` and `domain_expert` and `mode="task"` on `health_coach`, or build the multi-specialist path as a graph `Workflow`.** The installed version is 2.7.1. Upgrading to ≥2.12 also brings node confirmation, the SQLite memory service, and eval efficiency metrics. The default model `gemini-2.5-flash` is also behind: Agent Platform moved Memory Bank's default to Gemini 3.5 Flash on 2026-06-29.

**Platform rename** [primary]: Vertex AI is now **Gemini Enterprise Agent Platform** (announced at Cloud Next, Apr 2026). Agent Engine is now **Agent Runtime**, and Memory Bank, Sessions and Code Execution keep their names under the new platform ([name changes](https://docs.cloud.google.com/gemini-enterprise-agent-platform/vertex-ai-name-changes)). Use the new names in a 2026 README; "Vertex AI Agent Engine" now reads as dated. Agent Runtime supports long-running operations up to 7 days. From the [release notes](https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes): OTel tracing is on by default for ADK deploys (18 Jun 2026), and Agent Registry is GA with A2A 1.0 (18 Jun 2026).

---

## 2. Orchestration patterns: what counts as best practice now

### Findings
- **Centralised beats independent, and multi-agent hurts sequential reasoning.** Google Research and MIT ran 180 configurations across four benchmarks ([arXiv 2512.08296](https://arxiv.org/pdf/2512.08296), [Google blog](https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/), Dec 2025). Independent multi-agent setups amplified errors **17.2x**, against 4.4x for centralised (decentralised 7.8x, hybrid 5.1x), because the orchestrator acts as a "validation bottleneck". Centralised helped parallelisable financial reasoning, but **all multi-agent variants degraded sequential reasoning by 39–70%**. [benchmark]
- **Multi-agent pays off when it buys breadth and token budget.** Anthropic's research system (Opus lead, Sonnet subagents) beat single-agent Opus by 90.2% on breadth-first research. Token usage explained about 80% of variance, and multi-agent runs used about 15x the tokens of chat ([Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system)). [vendor/benchmark-internal]
- **The LangChain pattern taxonomy (Jan 2026)** still holds: subagents-as-tools (supervisor), handoffs, skills, router, and custom graph. It's covered in the prior note. [vendor]
- **Deterministic workflow plus LLM steps is now a first-class framework primitive.** ADK 2.0 `Workflow` graphs, LangGraph `StateGraph`, Pydantic Graph, and MS Agent Framework workflows (Sequential, Concurrent, Group Chat, Handoff, Magentic) all ship it. [primary]
- **Durable execution** [secondary, mostly vendor-adjacent]: [Cadenya](https://cadenya.com/other-content/durable-execution-for-ai-agents), [ZenML](https://www.zenml.io/blog/temporal-alternatives), [LangChain vs Temporal](https://www.langchain.com/resources/langgraph-vs-temporal).
  - **Temporal** gives the strongest guarantees (event-history replay) and has the heaviest operations burden.
  - **DBOS** is Postgres-as-truth and runs as a library.
  - **Restate** is a single binary.
  - **LangGraph checkpointers** give per-step state, `interrupt()`, and time travel, but not infrastructure-level guarantees. Practitioners pair it with Temporal, DBOS or Restate for long runs.
  - **ADK 2.x** now has workflow rehydration, resume, failed-node rerun and HITL confirmation (2.9–2.12) [primary], with session persistence through `DatabaseSessionService` (SQLite/Postgres) or Agent Platform Sessions.
  - Pydantic AI integrates eight durable backends [primary].
  - In every framework, resume reruns the node, so side effects must be idempotent. The ADK 2.9 and LangGraph docs both say so.
- **HITL**: ADK has `require_confirmation`, `RequestInput`, and tool confirmation. LangGraph has `interrupt()` + `Command(resume=)`. AG-UI 1.0 standardises HITL interrupts on the wire. [primary]

### Implications for this project
The PHA design (orchestrator over Data Science, Domain Expert and Coach) is *centralised*, which is the right family. But much of what the system does is sequential: compute, then interpret, then coach. Per the scaling study, a free-form LLM router is the riskiest way to wire that. The defensible design:
- a **graph `Workflow`** for the known pipelines (daily anomaly → prediction → next-day scoring → weight update; weekly digest), with LLM nodes only where judgment is needed;
- a **coordinator with `single_turn` specialists** for open-ended chat;
- an **ablation in the eval harness** against a single agent with all tools. That ablation is the evidence a reviewer will respect.

---

## 3. Protocols: real adoption vs hype

### 3.1 MCP [primary]
- **Current spec: 2026-07-28** (final, shipped 28 Jul 2026) ([MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28/)). This updates the prior note, which got the date right but missed the scope of the changes.
  - **Stateless core:** the `initialize` handshake and `Mcp-Session-Id` are gone. Each request carries version and capabilities, and optional `server/discover` lists them up front. Works behind round-robin load balancers.
  - **`Mcp-Method` / `Mcp-Name` headers** let gateways route without parsing the body. List responses carry `ttlMs` / `cacheScope` caching hints.
  - **Multi Round-Trip Requests** replace server-initiated sampling and elicitation.
  - **Formal Extensions:** Tasks (`io.modelcontextprotocol/tasks`), MCP Apps, and Enterprise Managed Authorization.
  - **Tool schemas** support full JSON Schema 2020-12.
  - **Auth:** RFC 9207 `iss` validation; CIMD replaces DCR, which is deprecated.
  - **Deprecated:** Roots, Sampling, Logging, and the legacy HTTP+SSE transport, each with at least 12 months of runway.
  - Tier-1 SDKs (TS, Python, Go, C#) supported it on release day.
- **Python SDK:** `mcp` **2.3.0** (2026-10-02), with the `MCPServer` API. FastMCP is at **4.1.1** (2026-10-18). `mcp` has about **235M** downloads a month and `fastmcp` about 53.7M [primary: pypistats]. ADK 2.11 adds opt-in MCP SDK 2.x connections.
- **Registry:** still **preview** (v0.1 API freeze; GA "later"). Third-party counts put it at 30–43K servers ([registry repo](https://github.com/modelcontextprotocol/registry); [secondary](https://www.localcan.com/blog/state-of-mcp-server-development)).
- **Code execution with MCP / "code mode"**: agents write code that calls tools instead of making one tool call per step. Anthropic reported a drop from 150K to 2K tokens (Nov 2025). An independent AIMultiple test found 78.5% fewer input tokens at equal success but about 7% higher latency ([AIMultiple](https://research.aimultiple.com/code-execution-with-mcp)). [vendor + benchmark] This is directly relevant to §5.
- **Verdict:** **justified.** MCP is table stakes. Expose the read-only health substrate as an MCP server (SDK v2, Streamable HTTP, resources for the schema, tools for queries) so Claude Desktop or Code and the ADK agent share one tool layer.

### 3.2 A2A
- **v1.0 shipped 12 Mar 2026** ([announcement](https://a2a-protocol.org/latest/announcing-1.0/)): multi-tenancy, signed Agent Cards, and JSON-RPC / REST / gRPC bindings. It became a Growth-stage project at AAIF (Linux Foundation) on 27 Aug 2026 ([blog](https://a2a-protocol.org/latest/blog/2026/08/27/a-new-chapter-for-a2a-joining-the-agentic-ai-foundation/)). `a2a-sdk` **1.2.3** (2026-10-19) has about **11.4M** downloads a month and the repo has 26.2K stars [primary]. Agent Platform Agent Registry supports A2A 1.0 (GA Jun 2026) [primary].
- **Reality check:** the June 2026 review at [agentndx](https://agentndx.ai/blog/a2a-protocol-adoption-mid-2026/) found "production-ready" means the tooling exists. The Linux Foundation cited production deployments without any counts, and a Credal analysis (Mar 2026) blamed weak adoption on limited use cases. [secondary] A2A's own docs say it is **"not a sub-agent or tool-call protocol"** [primary].
- **Verdict for this project:** the in-process specialists should **not** talk over A2A. A2A is justified only if you expose the whole health agent as an A2A server (`to_a2a`, an Agent Card) that a *different* client calls, such as a Claude Agent SDK or LangGraph agent. That cross-framework boundary is a legitimate, cheap demo of knowing where the protocol line sits.

### 3.3 AG-UI / A2UI
- **AG-UI 1.0** shipped 30 Sep 2026 ([CopilotKit](https://www.copilotkit.ai/blog/ag-ui-1-0)): stable JSON-Schema spec, subagents, HITL interrupts, and per-run token usage. `ag-ui-protocol` 1.0.0 is on PyPI (2026-09-17) and the repo has 16.7K stars [primary]. MS Agent Framework and Pydantic AI ship integrations [primary]. The adopter list (Google, Microsoft, AWS, Anthropic and others) is a vendor claim. **Justified only if you build a web front-end.** It's the standard event stream between agent and UI.
- **A2UI** (declarative UI from agents, Google): `a2ui-project/a2ui` has 16.7K stars and `@a2ui/lit` is at 0.14.0. The site lists v0.9.x as production and v1.0 as RC. Sources conflict. **Pre-1.0; skip or mention only.**

### 3.4 AP2 and agentic payments
- AP2 was donated to the **FIDO Alliance** on 28 Apr 2026, alongside Mastercard's Verifiable Intent. v0.2 added "human not present" payments ([FIDO](https://www.fidoalliance.org/fido-alliance-to-develop-standards-for-trusted-ai-agent-interactions/), [PaymentsJournal](https://www.paymentsjournal.com/google-donates-its-agentic-payments-protocol-to-the-fido-alliance/)). The GitHub repo `google-agentic-commerce/AP2` (3.2K stars) has had **no commits since 29 Apr 2026** [primary]. A tracker notes "no verified third-party production deployment" [secondary]. The adjacent protocols are UCP (Google and Shopify), ACP (OpenAI and Stripe), and x402. **Not relevant to a health agent. Mentioning it would read as protocol-collecting.** This also resolves the prior note's AP2 naming conflict: AP2 means *Agent Payments Protocol*.

---

## 4. Agent memory, state of the art

| System | Model | Current version / activity [primary] | Evidence quality |
|---|---|---|---|
| **Agent Platform Memory Bank** (formerly Vertex) | Managed LLM extraction with **consolidation** (merges, resolves contradictions), custom topics, few-shot examples, per-identity scope, TTL, revisions, memory profiles | GA Dec 2025; billing from Jan 2026 (pricing page cites 1 Sep 2026 for the current structure, conflict unresolved); IngestEvents GA and `gemini-embedding-2` 8 Jul 2026; profiles GA 15 Jul 2026 ([docs](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank), [release notes](https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes)) | Primary docs; no public benchmark found |
| **ADK memory services** | `InMemoryMemoryService`, `VertexAiMemoryBankService`, `VertexAiRagMemoryService`, **SQLite memory service (2.11)**; `PreloadMemoryTool` (each turn) vs `LoadMemoryTool` (on demand); populate via `add_session_to_memory` ([adk.dev](https://adk.dev/sessions/memory/)) | 2.11–2.12 | Primary |
| **Mem0** | Extract, then update (ADD/UPDATE/DELETE) over vector store, optional graph | `mem0ai` 2.2.1; 67.5K stars; 2.0M downloads a month | Self-reports 92–94% on LoCoMo/LongMemEval; its own report flags one figure as "not independently confirmed" ([Mem0](https://mem0.ai/blog/ai-memory-benchmarks-in-2026)) [vendor] |
| **Zep / Graphiti** | **Bi-temporal knowledge graph**: each fact edge has valid_at/invalid_at plus created_at/expired_at; hybrid semantic + BM25 + graph traversal; MCP server | `graphiti-core` 0.31.1 (2026-10-15); 32K stars; `zep-cloud` 4.0.0 | LoCoMo results range from 75% to 94.7% depending on who runs them. Vendor dispute with Mem0 unresolved. [vendor/disputed] Paper: [arXiv 2501.13956](https://arxiv.org/abs/2501.13956) |
| **Letta** (MemGPT) | Agent-editable memory blocks; sleep-time consolidation ("dreaming"); **Context Repositories** (git-versioned memory, Feb 2026) | 25.2K stars; `letta-client` 1.12.1 (Jun 2026) | Little independent benchmarking [secondary] |
| **LangMem** | LangGraph Store-based extraction and prompt optimisation | Last PyPI release 0.0.30 (**27 Oct 2025**); 2026 commits are dependency bumps only | **Stagnant.** LangChain's energy has moved to deepagents and LangGraph Store [primary] |

**Evals:**
- **LoCoMo** (shared haystack) compresses differences between systems. **LongMemEval** (isolation per question) separates them better.
- **MemoryAgentBench** (ICLR 2026, [arXiv 2507.05257](https://arxiv.org/html/2507.05257v3)) evaluates incremental multi-turn memory: accurate retrieval, test-time learning, long-range understanding, and conflict resolution.
- **EvoMemBench** reports that long-context baselines "remain highly competitive", that memory helps mainly when context is insufficient, and that no single memory form wins consistently. [benchmark]

**Implication.** Your learning loop is already a richer memory than any of these products for this domain. It produces dated predictions, journal outcomes, and per-signal weights, which together are episodic, outcome-labelled, and procedural memory. The state-of-the-art move is to formalise it:
- typed tables for **semantic** facts (baselines, user context), **episodic** records (predictions with outcomes), and **procedural** state (weights), all with **bi-temporal validity** in the Graphiti style ("baseline RHR was 58 valid from … to …"), stored in SQLite;
- access through a custom `BaseMemoryService` / `LoadMemoryTool`;
- a small **memory eval** in the MemoryAgentBench style (conflict resolution: "what was my baseline before the March change?").

Memory Bank can sit as an optional managed backend behind the same interface, which also proves the abstraction works. Avoid adding Mem0 or Zep as a dependency: that's vendor lock-in for no measurable gain at n=1.

---

## 5. Code-execution agents for data analysis

- **PHIA** (Merrill et al., [arXiv 2406.06464](https://arxiv.org/abs/2406.06464), v4 Sep 2025, "accepted to Nature Communications"): an agent with multistep reasoning, code generation and retrieval over wearable data. It scored **84% accuracy on objective numerical questions** and 83% favourable ratings on open-ended ones, was 2x as likely as a strong code-generation baseline to earn the top quality rating, and was evaluated with 650 hours of expert time over 4,000+ questions. [benchmark]
- **Personal Health Agent** ([arXiv 2508.20148](https://arxiv.org/pdf/2508.20148), Google): Data Science, Domain Expert and Health Coach agents, evaluated on 10 tasks with 7,000+ annotations and 1,100 expert and user hours, with PHIA re-implemented as a baseline. **This is the architecture `health_agent/agent.py` cites.** Its DS agent generates analysis code, so the repo's fixed-tool plus `run_sql` approach is a narrower version of it. [benchmark]
- **ADK executors** [primary, [adk.dev GKE](https://adk.dev/integrations/gke-code-executor/), API refs]:
  - `BuiltInCodeExecutor` (Gemini's native code execution: no custom libraries, no access to your DB);
  - `UnsafeLocalCodeExecutor` (development only);
  - `ContainerCodeExecutor` (Docker image, network can be disabled);
  - `GkeCodeExecutor` (gVisor, sandbox mode);
  - `AgentEngineSandboxCodeExecutor` (Agent Platform Code Execution: stateful per session, 14-day sandbox TTL).
  
  Known issue: [adk-python #5315](https://github.com/google/adk-python/issues/5315) reports that `AgentEngineSandboxCodeExecutor` fails with MALFORMED_FUNCTION_CALL on Gemini 2.x, because it expects markdown code blocks. The documented workaround is to call the sandbox API from a `FunctionTool` ([discussion #3935](https://github.com/google/adk-python/discussions/3935)). Agent Platform Shell and Computer-Use sandboxes went GA on 9 Sep 2026. Code Execution's own GA status is unconfirmed.
- **Third-party sandboxes:** E2B (`e2b-code-interpreter` 2.11.0, 14.5K stars, 2.5M downloads a month) is the usual pick for a stateful Jupyter-style interpreter. Modal is for GPUs, Daytona for persistent workspaces (its core went private in Jun 2026). OpenAI Agents SDK sandbox agents support E2B, Modal, Daytona, Docker and others [secondary/primary].
- **Recommendation:** give `data_scientist` a **sandboxed pandas executor** with these properties:
  - local: `ContainerCodeExecutor` with a read-only mount of a **de-identified extract or Parquet snapshot**, network off;
  - cloud: Agent Platform sandbox through a `FunctionTool` wrapper, which avoids #5315;
  - keep `run_sql` for cheap lookups;
  - add an eval slice that compares fixed-tools, SQL, and code-exec on PHIA-style numeric questions.

  That reproduces the paper's central finding on your own data and is the most credible engineering story the project can tell.

---

## 6. Comparison table for THIS project (solo, Python, GCP, SQLite, existing ADK code)

| Criterion | **ADK 2.12 (keep)** | LangGraph 1.2 (switch) | Pydantic AI 2.x | OpenAI Agents SDK | Claude Agent SDK |
|---|---|---|---|---|---|
| Migration cost from current repo | **None** (upgrade + delegation-mode fix) | High (rewrite agents, state, tools) | Medium–high | Medium–high | Medium (different paradigm: harness) |
| Multi-agent primitives | Coordinator + modes (chat/task/single_turn), graph Workflow, parallel | StateGraph, supervisor/swarm libs, subgraphs | Agent delegation + Pydantic Graph | Handoffs, agents-as-tools | Subagents (own context) |
| Durability / HITL | Resume, rehydration, `require_confirmation`, DB sessions; managed on Agent Runtime | **Best-in-class checkpointer**, interrupt, time travel | **8 durable backends** | Temporal integration GA | Sessions, fork |
| Eval built in | `adk eval`, trajectory, LLM-judge, efficiency metrics | Via LangSmith (SaaS) | pydantic-evals | Tracing; platform evals sunsetting | None built in |
| Gemini/GCP fit | **Native** (Memory Bank, Sessions, sandboxes, Agent Registry, OTel default) | Good via integrations | Good | Model-agnostic via LiteLLM, OpenAI-first | Claude-first |
| MCP / A2A | MCP SDK 2.x, native A2A (`RemoteA2aAgent`, `to_a2a`) | MCP adapters, A2A support | MCP, A2A (per AAIF) | MCP first-class | MCP first-class (in-process servers) |
| Hiring keyword strength | Differentiator (enterprise JDs) | **Highest** | Rising | Medium | Rising |
| Evidence posture | primary | primary + vendor | primary | primary + vendor | primary + secondary |

---

## 7. Recommendation

**Keep ADK as the orchestration layer, make it current, and put the "standard skills" signal into portable layers (MCP, an eval harness, OTel) rather than into a framework rewrite.** Concretely, in priority order:

1. **Upgrade `google-adk` from 2.7.1 to ≥2.12 and fix delegation semantics.** Set `mode="single_turn"` on `data_scientist` and `domain_expert` and `mode="task"` on `health_coach`. Or replace free routing with a small graph `Workflow` for the "compute → interpret → coach" path. Add a regression eval proving the orchestrator now synthesises across two specialists. *Evidence: [adk.dev collaboration](https://adk.dev/workflows/collaboration/); scaling study (sequential tasks degrade under loose multi-agent coordination).*
2. **Turn the learning loop into a deterministic ADK `Workflow`** with LLM nodes (detect anomaly → write a dated prediction → after the next-day journal, score → update weights), using `require_confirmation` where a human should approve weight changes, idempotent nodes, and a persisted `DatabaseSessionService` (SQLite). This shows "deterministic workflow + LLM steps + durable resume + HITL" in one feature that's actually yours.
3. **Add a sandboxed code-execution tool to `data_scientist`** (§5) and an ablation eval: tools-only vs SQL vs code-exec vs single-agent. This is the PHIA/PHA finding reproduced on n=1 real data.
4. **Expose the substrate as an MCP server** (official `mcp` 2.x `MCPServer`, Streamable HTTP, read-only, stateless per spec 2026-07-28). Have the ADK agent consume it through `McpToolset`, and document the Claude Desktop/Code config. This is one tool layer for two clients, and it covers the highest-volume protocol keyword with real engineering behind it.
5. **Memory:** use typed, bi-temporal SQLite memory behind ADK's memory-service interface (start from the 2.11 SQLite memory service), and keep **Memory Bank as an optional backend** you can A/B. Add 10–20 MemoryAgentBench-style conflict and temporal questions to the eval set.
6. **Optional, timeboxed to a day each:**
   - (a) wrap the agent with `to_a2a` and call it from a tiny LangGraph or Claude Agent SDK client. That genuine cross-framework boundary justifies A2A and adds the LangGraph keyword without a rewrite.
   - (b) AG-UI only if you ship a web UI.
   - Skip A2UI, AP2, Mem0/Zep, and CrewAI.

**Why not switch to LangGraph?** Its edge (checkpointer maturity, mindshare) is real but is mostly about keywords for this project. ADK 2.x now covers graph workflows, resume and HITL. You're on GCP with Gemini, and ADK hooks natively into Memory Bank, sandboxes, Agent Registry and OTel. Hiring evidence says framework names are "weak evidence now"; evals, failure retrospectives and outcomes convert. A rewrite spends the scarcest resource (solo time) on the lowest-signal layer. If LangGraph *demand* matters for target roles, option 6(a) buys the keyword honestly.

---

## 8. Uncertainties and gaps

- **Download and star trends:** I have a snapshot only (the pypistats time-series endpoint failed), so "rising/falling" is a judgement call. The OpenAI Agents SDK download count was unavailable.
- **Memory Bank billing date** conflicts: release notes say 28 Jan 2026, the pricing page says 1 Sep 2026.
- **Code Execution (Agent Platform) GA status** is unconfirmed. Issue #5315 may be fixed in later ADK releases; verify before relying on it.
- **A2A production adoption** is supported only by supporter counts and press releases; there are no usage metrics.
- **AG-UI adopter claims** are vendor-stated. **A2UI** version status conflicts between sources.
- **Memory benchmark numbers** are vendor-disputed. I found no independent head-to-head of Mem0, Zep, Letta and Memory Bank under one judge and model.
- **ADK 2.x `AgentTool`:** one third-party guide claims it's "discouraged in 2.0" in favour of modes. Not confirmed in official docs.
- **LangGraph 1.2 feature details** (node timeouts, error handlers, `response_schema`) come from a secondary source. The GitHub release page confirms only the recent durability and interrupt fixes.
- **Claude Agent SDK nested-subagent limits** (depth 3, concurrency 20) come from secondary sources only.
- **PHIA journal citation** (volume and year) is unverified. arXiv says only "accepted to Nature Communications".
