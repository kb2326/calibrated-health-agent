# 08 — Fact-check of high-stakes claims in notes 00–06

Checked on 2026-10-20 against primary sources (official docs, pricing pages, PyPI JSON, GitHub releases, official blogs). Files 00–06 were not edited. If a claim in 00–06 conflicts with this file, this file wins.

Verdicts: **confirmed** / **corrected** / **unverifiable**.

## Results table

| # | Claim (as stated in notes) | Verdict | Correct value / nuance | Primary URL | Seen |
|---|---|---|---|---|---|
| 1a | Gemini 3.5 Flash-Lite $0.30 in / $2.50 out per 1M | confirmed | $0.30 / $2.50 (standard paid tier). | https://ai.google.dev/gemini-api/docs/pricing | 2026-10-20 |
| 1b | Gemini 3.8 Flash $0.75 / $3.75, doubles 2027-01-01 | confirmed | Goes to $1.50 / $7.50 on Jan 1 2027. **Gemini 3.6 Flash, both 3.8 TTS models and Robotics ER 2 also double on that date.** | same | 2026-10-20 |
| 1c | Gemini 4 Argon prices double 2026-12-01 | confirmed | $2.00/$10.00 → $4.00/$20.00 on Dec 1 2026. No free tier. | same | 2026-10-20 |
| 1d | Gemini Embedding 2 $0.20 / 1M | confirmed (text only) | $0.20/1M is the **text** price. Image $0.45, audio $6.50, video $12.00 per 1M. | same | 2026-10-20 |
| 1e | "2.5 models legacy" | **corrected** | The models page says the 2.5 models "are not deprecated and will continue to be served until further notice". Access is limited to users who have used them before, and new projects are steered to 3.5 Flash-Lite / 3.8 Flash. The models labelled legacy are 3 Flash Preview (on the pricing page), 3.1 Flash Live/TTS previews, Veo 3.1 and Lyria 3. | https://ai.google.dev/gemini-api/docs/models | 2026-10-20 |
| 1f | Free-tier data is used to improve Google products | confirmed | Free tier: "Yes" for most models. Paid tier: "No". The invite-only Contributor tier is also "Yes". | pricing page | 2026-10-20 |
| 2a | Vertex AI renamed Gemini Enterprise Agent Platform (2026-04-22) | confirmed | Release-notes entry dated Apr 22 2026 (Cloud Next '26): "Vertex AI is now part of Gemini Enterprise Agent Platform". Also Vertex AI Studio → Agent Studio, and Memory Bank → Agent Platform Memory Bank. | https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes | 2026-10-20 |
| 2b | Agent Engine → Agent Runtime | confirmed | "Agent Runtime on Gemini Enterprise Agent Platform". The API resource is still `ReasoningEngine` (secondary source). | https://docs.cloud.google.com/gemini-enterprise-agent-platform/vertex-ai-name-changes | 2026-10-20 |
| 3a | google-adk latest 2.12.0, released 2026-10-13 | confirmed | 2.12.0 uploaded 2026-10-13 16:42 UTC. Earlier releases: 2.11.0 on 10-02 and 2.10.0 on 09-25. | https://pypi.org/pypi/google-adk/json ; https://github.com/google/adk-python/releases/tag/v2.12.0 | 2026-10-20 |
| 3b | sub_agents default mode "chat"; `mode="single_turn"` and `"task"` exist | confirmed | Chat is the default when an agent is used as a sub-agent; single_turn is the default when it is a workflow node. Modes are "chat", "task" and "single_turn". Task mode is disabled inside graph workflows. | https://adk.dev/workflows/collaboration/ ; https://adk.dev/agents/llm-agents/ | 2026-10-20 |
| 3c | ADK graph Workflow plus `require_confirmation` (2.12) | confirmed | Graph engine since 2.0. 2.12 release notes: "Require human confirmation before executing workflow nodes via `require_confirmation`" (on `@node` / FunctionNode). | GitHub release v2.12.0 ; https://adk.dev/graphs/human-input/ | 2026-10-20 |
| 3d | `ag-ui-adk` package exists (first-party bridge) | confirmed (with nuance) | PyPI `ag-ui-adk` 0.10.0 (2026-10-18), "ADK Middleware for AG-UI Protocol". It is maintained in the **ag-ui-protocol** repo, not by Google's ADK team, so "first-party" overstates it. It is still pre-1.0. | https://pypi.org/pypi/ag-ui-adk/json | 2026-10-20 |
| 4a | MCP spec 2026-07-28 (stateless) | confirmed | Final spec released 2026-07-28. It drops the initialize handshake and sessions, and adds server/discover, MRTR, and Mcp-Method/Mcp-Name headers. | https://blog.modelcontextprotocol.io/posts/2026-07-28/ | 2026-10-20 |
| 4b | Python SDK `mcp` 2.3.0 | confirmed | 2.3.0 uploaded 2026-10-02. 2.0.0 shipped 2026-07-28, and 2.2.0 on 2026-09-07. | https://pypi.org/pypi/mcp/json | 2026-10-20 |
| 4c | A2A v1.0 on 2026-03-12 | confirmed | The GitHub v1.0.0 changelog is dated 2026-03-12. The Linux Foundation announcement post came on 2026-03-19. v1.0.1 followed in late May 2026. | https://github.com/a2aproject/A2A/releases | 2026-10-20 |
| 4d | AG-UI 1.0 on 2026-09-30 | confirmed | CopilotKit post dated 2026-09-30. Its URL is `/blog/ag-ui-1.0`; the `ag-ui-1-0` URL in note 02 returns 404. | https://www.copilotkit.ai/blog/ag-ui-1.0 | 2026-10-20 |
| 5a | Cloud Run direct IAP GA 2026-03-13 | confirmed | Release notes, Mar 13 2026: direct IAP on Cloud Run without a load balancer is GA. | https://docs.cloud.google.com/run/docs/release-notes | 2026-10-20 |
| 5b | Cloud Run budget spend caps GA 2026-10-12 | confirmed | Preview 2026-07-27, GA 2026-10-12. Cloud Billing's notes say GA covers only "a limited set of services". | same | 2026-10-20 |
| 5c | Google Health API webhooks (signed, retried up to 7 days) | confirmed (nuance) | HTTPS POST with a `GOOGLE-HEALTH-API-SIGNATURE` header (Tink ECDSA P-256, keys rotate every 30 days) plus an optional Authorization secret. The endpoint must return 204. Retries use exponential backoff for up to 7 days. The payload is not purely a signal: it carries user ID, data type, operation (UPSERT/DELETE) and intervals, but no data values. | https://developers.google.com/health/webhooks | 2026-10-20 |
| 5d | OAuth Testing mode means 7-day refresh-token expiry | confirmed | "the refresh tokens issued are time-based and expire after 7 days". Unverified apps are capped at 100 users. | https://developers.google.com/health/setup | 2026-10-20 |
| 6 | Professional Agentic Architect cert: GA mid-Nov 2026, $200 | confirmed (nuance) | Still in **beta** today at $120, which is 40% off the "$200 retail price". GA exam and registration launch mid-November; the page doesn't state a GA price, though $200 is implied. Valid for 1 year. Hybrid format: ~80 MCQ in 3 h plus hands-on labs due by 2026-12-31. | https://cloud.google.com/learn/certification/agentic-architect | 2026-10-20 |
| 7a | Next.js 16 is current | confirmed | Latest is 16.4 (2026-10-06). No Next.js 17. There were security releases on 2026-09-30 and 2026-10-14, so pin a patched 16.4.x. | https://nextjs.org/blog | 2026-10-20 |
| 7b | ty in beta, 0.0.89 on 2026-10-16 | confirmed | PyPI classifier "Development Status :: 4 - Beta". 0.0.89 released 2026-10-16. | https://pypi.org/pypi/ty/json ; https://github.com/astral-sh/ty/releases | 2026-10-20 |
| 7c | Astral **acquired** by OpenAI (2026-03-19) | **corrected** | An **agreement to acquire** was announced 2026-03-19. Closing depends on regulatory approval, and I found no closing announcement from either company. Write "agreed to acquire". | https://openai.com/index/openai-to-acquire-astral/ ; https://astral.sh/blog/openai | 2026-10-20 |
| 7d | Material for MkDocs in maintenance mode, with fixes until **2026-11-05** | **corrected** | Maintenance mode is confirmed, and new feature work goes to Zensical. But end-of-life has been **extended to 2027-05-05**. | https://github.com/squidfunk/mkdocs-material/issues/8523 | 2026-10-20 |
| 7e | SDV under Business Source License | confirmed | BSL 1.1 ("not an Open Source license"). It changes to MIT four years after each release. | https://github.com/sdv-dev/SDV/blob/main/LICENSE | 2026-10-20 |
| 8a | "MCP 721, RAG 707, LangGraph 381 of 2,664 agentic roles" | confirmed | Get Ready For Agents index, Oct 2026: 2,664 roles across 197 companies (257 tracked), ~70% of 3,779 AI postings. MCP 721, RAG 707, LangChain 471, LangGraph 381. It is a weekly snapshot, so the numbers will drift. | https://www.getreadyforagents.com/statistics | 2026-10-20 |
| 8b | LangGraph 35.8–37.9% on Skillenai | confirmed (tiny n) | Agent Engineer 37.9% is **11 of 29** postings. Agentic AI Engineer 35.8% is **24 of 67** (note 01 says the bucket is 65). 90 days to 2026-10-13, 2,228 LangGraph postings. Treat the percentages as noisy. | https://skillenai.com/data/skill/langgraph | 2026-10-20 |
| 9a | PHIA 22% / 74% / 84%, Nature Communications 2026 | confirmed | Nat Commun 17, 1143, published 2026-01-12, DOI 10.1038/s41467-025-67922-y. Numerical reasoning 22%, code-generation baseline 74%, PHIA 84% exact match (n=4,000). This settles the "journal citation unverified" caveat in note 02. | https://pmc.ncbi.nlm.nih.gov/articles/PMC12855967 | 2026-10-20 |
| 9b | Google/MIT multi-agent study: −39–70% on sequential tasks, error amplification 17.2x (independent) vs 4.4x (centralized), 180 configs / 4 benchmarks | confirmed for the blog; nuance | The Google Research blog (2026-01-28) gives all four figures. The **current arXiv abstract (2512.08296) is a revised version**: 260 configurations across 6 benchmarks, range +80.8% to −70.0%, and it doesn't state 17.2x/4.4x. The blog doesn't name MIT ("Google Research, Google DeepMind, and academia"). | https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/ ; https://arxiv.org/abs/2512.08296 | 2026-10-20 |

## Notes

1. **Corrections to carry into the plan:**
   - The 2.5 models are not "legacy". They are restricted to existing users but still served until further notice.
   - Astral has an announced, not completed, acquisition by OpenAI.
   - Material for MkDocs EOL is 2027-05-05, not 2026-11-05. The "skip Material" recommendation still holds because it is in maintenance mode.
2. **Precision fixes (claim is right but incomplete):**
   - Embedding 2's $0.20 is the text-only price.
   - Gemini 3.6 Flash doubles on 2027-01-01 too.
   - The Agentic Architect cert currently costs $120 (beta). $200 is the retail/GA price.
   - Spend caps GA covers only a limited set of services.
   - Health API webhooks include metadata (type, operation, intervals), not just a ping.
   - `ag-ui-adk` comes from the AG-UI project, v0.10.0, not Google's ADK team.
3. **Citing the multi-agent study:** if you quote 17.2x/4.4x or "180 configurations", cite the Google Research blog, not the arXiv abstract. The arXiv version now reports 260 configurations and 6 benchmarks.
4. **Small sample:** the Skillenai role-share percentages rest on 29–67 postings per role. Prefer the GRFA counts (721/707/381) when citing demand.
5. **Vertex pricing:** prices were checked on the Gemini Developer API pricing page only. The Vertex/Agent Platform pricing page was not separately cross-checked, and its prices may differ (for example, regional prices and enterprise SKUs).
6. **Broken link:** `https://www.copilotkit.ai/blog/ag-ui-1-0` (note 02) returns 404. The correct URL is `/blog/ag-ui-1.0`.
