# 01 — Hiring Signals for AI / Agentic AI / Applied AI Engineers (late 2026)

Research date: 2026-10-20. Builds on `research_notes/Health agent portfolio revamp/portfolio hiring signals.md` (2026-10-19), which is called the **prior note** below. This file checks the prior note against newer sources, updates it, and corrects it where needed. It does not repeat it.

Evidence labels used on every claim:
- **[job-data]**: counts from job-posting indexes or primary job descriptions
- **[HM-quote]**: a hiring manager or recruiter writing in the first person, or a named hiring guide
- **[vendor]**: a vendor, course seller, or recruiting firm with a commercial interest
- **[adoption]**: package-download or ecosystem data. This measures what developers use, not what employers ask for.
- **[anecdote]**: a single thread or post
- **[primary-doc]**: an official Google, Anthropic, etc. document

---

## Executive summary

1. **The core stack keywords hold, and newer data makes them stronger.** The Get Ready For Agents index (Oct 2026) now counts **2,664 agentic roles at 197 companies, 70% of tracked AI roles**. Top skills: Python 1,324, Cloud 928, **MCP 721**, RAG 707, Kubernetes 539, TypeScript 477, LangChain 471, Multi-agent 450, **LangGraph 381**. MCP rose 16% from the prior note's 624. **[job-data]** On HN "Who is hiring", MCP went from about 0% of posts (Nov 2025) to **5% (Oct 2026)**. Evals doubled from 1–3% to **4–6% since June**. "Agentic coding" is a new requirement at 3–5%. **[job-data]**
2. **Within agent roles, LangGraph is the leading framework in job postings, but Google ADK is now a mainstream framework, not a niche one.** In Skillenai's role data, LangGraph appears in **35.8% of "Agentic AI Engineer" postings and 37.9% of "Agent Engineer" postings**. CrewAI appears in 30.8%, MCP in 17.2%. **[job-data]** No index publishes an ADK posting count (a gap). On PyPI, however, google-adk gets **10.1M downloads/month**, close to openai-agents at 12.4M and well above crewai at 2.4M. **[adoption]** Citi lists ADK first in its Lead Agentic AI Engineer JD. Google's new certification is built around ADK. **[job-data] [primary-doc]**
3. **Correction to the prior note: GCP is the #3 cloud by volume. For Gemini-platform skills specifically, though, demand is close to AWS.** Across all postings: AWS 34,054, Azure 17,287, GCP 12,766 (Skillenai, 90 days). **[job-data]** For managed GenAI platforms, jobspipe counts **Vertex AI 12,060** postings vs **Amazon Bedrock 11,211** vs **Azure OpenAI 12,509**, roughly a three-way tie. **[job-data]** "Agent Engine" no longer exists under that name: Google's official exam guide lists **"Agent Runtime (formerly Agent Engine)"**, and Vertex AI is now the **Gemini Enterprise Agent Platform** (since Cloud Next, Apr 2026). **[primary-doc]** A README that says "Vertex AI Agent Engine" already looks out of date.
4. **New fact: Google launched a *Professional Agentic Architect* certification.** The beta ran Sep 8–30, 2026, with GA in mid-Nov 2026. It costs $200, is valid for **1 year**, and requires **both a multiple-choice exam and hands-on labs**. Domains: custom agents with ADK 33%, eval and deploy 22%, coding agents 17%, security and governance 15%, low-code 13%. **[primary-doc]** Of Google's certifications, this one matches the project most closely. PMLE was refreshed on Jun 1, 2026 to cover the Agent Platform, RAG, and GenAI eval. The Generative AI Leader certification is a business credential and says little about engineering ability. No hiring guide I found treats certifications as a deciding factor. **[HM-quote] [vendor]**
5. **What converts to interviews has not changed: proof that you can ship, measure, and defend your choices.** Bouchard (updated 28 Aug 2026): framework names "are weak evidence now"; "Cost belongs in the same evaluation"; "'The agent chose it' is not an answer." **[HM-quote]** KORE1, a recruiter with 142 placements: candidates should "estimate inference cost within 30%," and eval discipline is the #1 screen. **[HM-quote/vendor]** HeroHunt (Aug 2026) lists as green flags a **published MCP server**, merged framework PRs, owned cost and latency metrics, and "hard-won simplicity." **[vendor]**
6. **A red flag the prior note missed: multi-agent for its own sake.** Bouchard (Jan 2026, reviewed Jul 2026) argues that "multi-agent is becoming the new overengineering" and says multiple agents are justified only by "real parallelism, overloaded context, external integration, or hard separation requirements." Anthropic, OpenAI, and Shopify guidance all say to start with a single agent. A multi-agent health system needs a **measured single-agent baseline** to answer this objection. **[HM-quote] [primary-doc]**
7. **Health-data MCP servers are already common.** GitHub already has a `fitbit-mcp` (its README mentions the Google Health API migration), 8+ Oura MCP servers, and Open Wearables (551★). Google Research published a three-agent "Personal Health Agent" design (arXiv 2508.20148). **[anecdote/primary-doc]** The data connector or the MCP server alone will not set this project apart. The differentiators are **evals on real longitudinal data, comparison against a published baseline architecture, and honest statistics** (n-of-1 correlation caveats).

---

## 1. Most-demanded skills and tools (quantified)

### 1a. Aggregate indexes (refreshed vs. prior note)

| Index (date) | Universe | Key numbers | Label |
|---|---|---|---|
| Get Ready For Agents / Agentic Ready, statistics page (Oct 2026) — https://www.getreadyforagents.com/statistics | 2,664 agentic roles, 197 hiring companies out of 257–270 tracked (Forbes AI50 + CB AI100 + F500 panel); a role counts as agentic only on a "hard signal" in the JD | Python 1,324 · Cloud 928 · MCP 721 · RAG 707 · Kubernetes 539 · TypeScript 477 · LangChain 471 · Multi-agent 450 · LangGraph 381 · Prompt eng. 354. Top hirers: Salesforce 231, Databricks 147, Intercom 103, OpenAI 88, Palantir 77, Cisco 73, Capital One 72, Citi 70 | [job-data] |
| Same index, jobs page (Oct 2026) — https://www.getreadyforagents.com/jobs | 3,779 AI roles | 70% agentic; 48 "new agentic job titles" that only one company uses so far; refreshed weekly; CC BY 4.0 | [job-data] |
| Same index, agent-engineer role page — https://www.getreadyforagents.com/jobs/roles/agent-engineer/ | snapshot of 12 Jun 2026 | "371 open agent engineer roles across 47 companies… Only 32 of the 371 (9%) are remote." Skills listed: orchestration/runtime, voice agents, **evals**, safety/governance hooks | [job-data] |
| Skillenai, MCP (90d to 2026-10-15) — https://skillenai.com/data/skill/model-context-protocol-mcp | indexed postings | 867 postings (+5.8% share vs. prior 4 wks). Co-occurs with Python 429, prompt eng. 209, CI/CD 183, **LangGraph 162**, RAG 161, LangChain 160, AWS 157. Role prevalence: AI Security Researcher 20.8%, **Agentic AI Engineer 17.2%**, Full-Stack AI Engineer 13.0% | [job-data] |
| Skillenai, LangGraph (90d to 2026-10-13) — https://skillenai.com/data/skill/langgraph | | 2,228 postings (+1.3%). Share of role's postings: Agent Engineer **37.9%**, Agentic AI Engineer **35.8%**, Generative AI Engineer 32.1% | [job-data] |
| Skillenai, CrewAI (90d to 2026-10-14) — https://skillenai.com/data/skill/crewai | | 793 postings (−0.2%). Agentic AI Engineer 30.8% (20/65), AI Agent Engineer 9.2% | [job-data] |
| Skillenai, LangChain — https://skillenai.com/data/skill/langchain | | Agentic AI Engineer: 40.0% (26/65); LangChain-wide share −0.6% | [job-data] |
| Skillenai, LLM evaluation (90d to 2026-10-13) — https://skillenai.com/data/skill/llm-evaluation | | 572 postings, **+8.4% share** vs. prior 4 wks (fastest-rising of those checked); co-occurs with observability (98) | [job-data] |
| Skillenai, clouds (90d to 2026-10-19) — https://skillenai.com/data/skill , https://skillenai.com/data/skill/gcp | all postings | AWS 34,054 · Azure 17,287 · GCP 12,766 (+3.2%) · observability 14,537 | [job-data] |
| HN Who-is-Hiring term shares, 12 months (updated 2026-10-19) — https://www.solheimsolutions.no/notes/hn-who-is-hiring/ | ~230–410 posts/month, startup-skewed | MCP 0→**5%**; Evals 1–3%→**4–6%** since Jun; "AI agent" 13–18% since Apr; RAG flat 1–4%; **Azure/AWS AI 0–1%**; Governance 0–1%; Agentic coding 1–2%→3–5% | [job-data] |

**Caveat:** Skillenai's "Agentic AI Engineer" bucket has only **65 postings**, so its role-share percentages are noisy. GRFA counts are much larger but come only from big companies.

### 1b. Company-level comparison (jobspipe.dev, "as of 25 Sep 2026", last-seen to 18 Oct) — https://jobspipe.dev/technologies.md [job-data]
jobspipe reads each posting and counts a company–technology pair only when two independent checks agree.

| Technology | Postings naming it | Companies (confirmed) |
|---|---|---|
| MCP | 32,958 | 7,682 (1,314) |
| LangGraph | 20,130 | 5,450 (1,084) |
| OpenTelemetry | 14,893 | 3,900 (820) |
| Azure OpenAI | 12,509 | 3,706 (607) |
| **Vertex AI** | **12,060** | 2,706 (431) |
| Amazon Bedrock | 11,211 (411 at AWS itself) | 2,926 (526) |
| CrewAI | 7,867 | 2,454 (395) |
| LangSmith | 3,774 (298 at LangChain itself) | 1,087 (222) |
| Temporal | 3,236 | 858 (222) |

Not indexed: Google ADK, OpenAI Agents SDK, Claude Agent SDK, Pydantic AI, A2A, Langfuse, Braintrust, Ragas, DeepEval, Azure AI Foundry. For these, demand has to be inferred from named JDs and adoption data. Top LangGraph employers: LangChain 298, TCS 141, **Citi 135**, Accenture 123, JPMorgan 121. Top MCP employers: EPAM 216, JPMorgan 199, Roku 160. *Inference:* enterprise banks and consultancies supply most of the volume for these keywords. Temporal employers include **Hinge Health (24)** and Lila Sciences (43), which is relevant to a health-domain project.

### 1c. Developer adoption (pypistats.org `recent` API, fetched 2026-10-20) [adoption]
Downloads include CI runs and transitive installs. langsmith is pulled in by langchain, and mcp is pulled in by most SDKs. Use these only as a rough signal of where the ecosystem is going.

| Package | Downloads, last month |
|---|---|
| mcp | 235.2M |
| langchain | 170.5M |
| langsmith | 77.2M |
| langgraph | 44.8M |
| temporalio | 38.1M |
| claude-agent-sdk | 29.8M |
| langfuse | 23.6M |
| openai-agents | 12.4M |
| a2a-sdk | 11.4M |
| **google-adk** | **10.1M** |
| ag-ui-protocol | 7.4M |
| pydantic-ai | 5.4M |
| deepeval | 2.6M |
| crewai | 2.4M |
| ragas | 1.1M |
| arize-phoenix | 0.6M |

*Inference:* CrewAI shows up often in JDs (30.8% of the small Agentic-AI-Engineer bucket) while its downloads are falling behind. JD keyword lists lag the tools developers actually use. ADK, the Claude Agent SDK, and Pydantic AI have real usage that JD indexes don't yet measure.

### 1d. Named postings (new beyond prior note)
- **Google**: ADK team postings (SWE II ADK, Warsaw; Senior SWE "AI Agent Ecosystem, ADK"; EM ADK); "Senior Applied AI Agent Engineer, GCP"; and a "Forward Deployed Engineering Intern, Summer 2027" building multi-agent systems and **evaluation pipelines** — https://www.google.com/about/careers/applications/jobs/results/105831903721857734-senior-software-engineer-ai-agent-ecosystem-adk , https://www.google.com/about/careers/applications/jobs/results/75665705386549958 . I could not fetch the full JD text, so these details come from search snippets. [job-data]
- **Anthropic, Applied AI Engineer** (several postings, Jan–Oct 2026). One "Beneficial Deployments" posting lists advising on "evals, agent architectures, context engineering, cost optimization" and building "benchmarks, MCP's, and Agent Skills". Most require 4+ years as a SWE, FDE, or technical founder — https://jobs.generalcatalyst.com/companies/anthropic/jobs/81748657-applied-ai-engineer (via aggregator; I did not verify it on Greenhouse). [job-data]
- **Anthropic, SWE Agent SDK (Claude Code)**: $320k–$485k, now closed — https://jobs.accel.com/companies/anthropic/jobs/68345347-software-engineer-agent-sdk-claude-code [job-data]
- **HN Oct 2026 thread**: Mastra (TS agent framework with evals and tracing); a marketplace role listing "LangChain/LangGraph/LlamaIndex/CrewAI (your choice)… evals and monitoring"; a frontier-evals role — https://news.ycombinator.com/item?id=49922569 [job-data]
- Prior-note JDs (Citi Lead Agentic: ADK + LangGraph + MCP + A2A + OTel; Deloitte Healthcare agentic; Verizon MCP servers) still make the clearest case for ADK, A2A, and OTel together. I did not re-verify that they are still open.

### 1e. Protocols, durable execution, cloud
- **MCP**: required at volume (see above). [job-data]
- **A2A**: >150 orgs by Apr 2026 (LF press release) — https://www.prnewswire.com/news-releases/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year-302737641.html [vendor]. a2a-sdk has 11.4M downloads/month [adoption]. It is in Google's cert syllabus [primary-doc]. No job index counts it; it appears in individual enterprise JDs (Citi, Booz Allen per search snippets). **This is a skill that sets you apart, not one employers assume.** The governance timeline is contested: AAIF transfer on 20 Aug 2026 vs. LF in Jun 2025 (https://enterprisedna.co/resources/news/google-a2a-aaif-agent-protocol-open-standard-august-2026/).
- **AG-UI**: 7.4M downloads/month [adoption]. I found **no JD evidence** for it. Treat it as an implementation detail, not a hiring keyword.
- **Temporal / durable execution**: 3,236 postings across 858 companies [job-data]. KORE1 puts Temporal in the stack for a multi-agent or platform hire at $240K–$325K+ (https://www.kore1.com/hire-agentic-ai-engineers-2026/) [vendor]. It is a real but narrow signal, strongest for platform roles. Ordinary JDs usually phrase it as "retries, checkpointing, state, recovery".
- **Cloud agent platforms**: I found **no posting-level comparison of AgentCore vs. Agent Runtime vs. Foundry Agent Service**; every comparison is vendor content (e.g., https://agentmarketcap.ai/blog/2026/04/07/azure-ai-foundry-enterprise-agent-platform-2026). Proxy: Vertex AI ≈ Bedrock ≈ Azure OpenAI by posting count (table 1b). HN startups almost never name cloud AI platforms (0–1%). *Inference:* the choice of cloud matters less than the transferable skills (agent runtime, IAM, tracing, eval pipeline). GCP is a reasonable choice, and the README should say which parts carry over to other clouds.

---

## 2. What separates a standout agentic portfolio from a tutorial clone

Confirmed against newer or additional sources:

- **Ship, measure, defend still holds.** Bouchard's article was re-reviewed on **28 Aug 2026** and is unchanged: framework names are "weak evidence now"; "A demo that worked on one cherry-picked example tells an interviewer almost nothing"; "Cost belongs in the same evaluation", with Cursor's benchmark as the example (63.2% at $0.55 vs. 64.8% at $11.02/task); "'The agent chose it' is not an answer." He wants agent-assisted workflows to come with tests, evals, and linters — https://www.louisbouchard.ai/what-i-look-for-when-hiring-ai-engineers/ [HM-quote]
- **Cost estimation and real failures.** KORE1 (Robert Ardell, updated 6 Aug 2026; based on 142 placements): eval discipline "is what separates the engineer who ships and the engineer who breaks production silently"; red flags include being unable to "estimate inference cost within 30%", never having handled a production failure such as an upstream rate-limit change, "defaulting to the most complex architecture", and framework knowledge from a previous cycle. Its sample JD requires "an eval harness measuring response quality on at least a 500-question reference set." It mentions no certifications — https://www.kore1.com/how-to-hire-ai-engineer-2026/ [HM-quote/vendor]
- **Artifacts that read as legitimate.** HeroHunt (6 Aug 2026), green flags: shipped agents with owned metrics ("per-invocation cost from eleven cents to four cents"); LLM-as-judge plus a ground-truth set; **a published MCP server or registry entry**; merged PRs to agent frameworks; state, retries, HITL, and stopping conditions; "hard-won simplicity". Red flags: a long framework list with no depth, adjectives instead of metrics, notebooks and stateless single calls, no named observability tool, the "vibe coding trap", being unable to explain how a tool fails mid-task. Interview loops use a **seeded-bug review take-home** — https://www.herohunt.ai/blog/how-to-recruit-ai-agent-engineers-in-2026/ [vendor]. This lines up with the prior note's r/ExperiencedDevs anecdote.
- **Interview loops re-run your evals.** FDE and applied-AI loops are typically a 3–8 hour take-home (often a RAG or tool agent with escalation to a human), then a technical deep-dive on "token cost, latency, evals, and failure modes", then a customer case study, which is the round that most often decides offers. Graders prefer "a well-documented partial solution above an undocumented complete one." OpenAI's FDE take-home reportedly includes a recorded walkthrough — https://www.aced.io/blog/forward-deployed-engineer-interview-the-definitive-2026-guide-fde , https://careerservices.fas.harvard.edu/blog/2026/08/01/forward-deployed-engineer-interview-the-definitive-2026-guide-fde/ [vendor/secondary]. **A partial correction to the prior note:** it found no evidence on demo videos. A recorded walkthrough is a *required* artifact in at least one lab's FDE loop, so a 3–5 minute walkthrough video is now a reasonable addition.
- **Small eval sets count.** Even "30 to 50 hand-curated examples" beats a happy-path screenshot (https://aitechconnect.in/tips/ai-evals-portfolio-proof-of-work-2026) [vendor]. Bouchard says as few as about 10 examples, with ground truth and 2+ approaches compared [HM-quote]. KORE1's 500 is the enterprise bar. *Reconciliation:* 10–50 is enough for a portfolio as long as the method is solid. Larger sets are expected for production claims.
- **Judging the judge.** Interviewers for evals roles may hand you a rubric and ask what is wrong with it. Calibrating an LLM-as-judge against human labels is the distinguishing skill — https://jobsbyculture.com/blog/ai-evals-engineer-career-guide-2026 [vendor]

---

## 3. Standout public projects (2026) and why

There is still **no verified case of "this repo got this person hired".** The prior note found the same gap. The closest evidence:
- **Google Research "Personal Health Agent"** (arXiv 2508.20148): orchestrator + Data Science + Domain Expert + Health Coach agents built on Fitbit-community query taxonomies. Secondary sources report that experts preferred it in 80% of evaluations — https://arxiv.org/pdf/2508.20148v2 , https://www.themomentum.ai/blog/personal-health-agents-googles-framework-and-the-future-of-connected-health-data [primary-doc + secondary]. **Its value to the project: a published baseline architecture and eval design to replicate at small scale and compare against.**
- **Open Wearables** (Momentum): a self-hosted multi-device API plus MCP server, 551★ at v0.3.0. It stands out because it is real infrastructure that others adopt — https://www.themomentum.ai/blog/open-wearables-0-3-alpha-flutter-sdk-for-apple-health-and-mcp-server-now-available [vendor]
- **Wearable MCP servers already exist**: `davidmosiah/fitbit-mcp` (activity, sleep, HR, HRV, SpO2, weight; notes the Google Health API migration), 8+ Oura servers — https://github.com/davidmosiah/fitbit-mcp , https://github.com/MykalMachon/oura-mcp [anecdote]. **There is little room left for a plain data connector.**
- **Active research**: VitalAgent (arXiv 2605.29483) and a task-oriented multi-agent wearable framework (arXiv 2609.24107) [primary-doc]. *Inference:* citing and benchmarking against these shows you can work at a research-adjacent level, which Feinberg's frontier-lab advice in the prior note asks for.
- The ecosystem audit gap: an awesome-list audit (Sep 2026) reports that "60% of harnesses ship without tests or evals" — https://github.com/ai-boost/awesome-harness-engineering [anecdote]. Shipping one with evals puts you in the minority.

---

## 4. GCP certifications: what carries weight now

| Credential | Status (Oct 2026) | Signal for an AI/agent engineer | Evidence |
|---|---|---|---|
| **Professional Agentic Architect** | Beta Sep 8–30; **GA mid-Nov 2026**; $200; **1-yr validity**; MCQ + **mandatory hands-on labs** (<5h, within 2 months); recommends 3+ yrs cloud incl. 1+ yr building agents on GCP | Highest *topical* match: ADK, Agent Runtime, Memory Bank, A2A/MCP, ADK evalsets, Gen AI eval service, Cloud Trace, Model Armor, Agent Identity/Gateway/Registry, HITL. It is new, so I found no evidence yet of employers recognizing it | [primary-doc] https://cloud.google.com/learn/certification/agentic-architect , https://support.google.com/cloud-certification/answer/18080541 , exam guide PDF https://services.google.com/fh/files/misc/professional_agentic_architect_exam_guide_english.pdf |
| Professional ML Engineer | $200; guide refreshed **Jun 1 2026** for the Agent Platform, RAG, GenAI eval, prompt and context engineering; 3+ yrs recommended | "Strong, senior technical signal" (getAIwork qualitative rating) | [vendor] https://getaiwork.com/articles/google-ai-certifications/ (1 Sep 2026), https://pdfquiz.com/blog/google-cloud-machine-learning-engineer-exam-changes-2026 |
| Generative AI Leader | $99, 3 yrs, conceptual, no technical prerequisite | A business credential with little engineering signal; "Good, especially in Google Cloud shops" | [vendor/primary-doc] |
| Skill badges (e.g., "Engineer AI Agents with ADK: Challenge Lab") | free/cheap | "Low on their own, useful as evidence of practice" | https://www.skills.google/focuses/145032 ; getAIwork [vendor] |

No hiring guide I read (Bouchard, KORE1, HeroHunt, Feinberg via prior note) lists certifications as a screening criterion. KORE1 and HeroHunt don't mention them at all. *Inference:* a certification is a tiebreaker at GCP partners and consultancies (Accenture, Quantiphi, and Infosys top the Vertex AI employer list), not a replacement for a project. The Agentic Architect exam guide is still useful as a free **syllabus for the build**.

**Naming is now part of being current [primary-doc]:** use Gemini Enterprise Agent Platform (formerly Vertex AI), **Agent Runtime (formerly Agent Engine)**, Agent Search (formerly Vertex AI Search), Agent Platform Memory Bank, and Agents CLI. Background on the rename: https://www.hpcwire.com/aiwire/2026/04/23/google-unveils-gemini-enterprise-agent-platform/

---

## 5. Red flags (consolidated, with new items marked NEW)

| Red flag | Source | Label |
|---|---|---|
| Framework list with no depth / "weak evidence" | Bouchard (Aug 2026); HeroHunt (Aug 2026); KORE1 "framework knowledge from a past cycle" | HM-quote / vendor |
| NEW: **multi-agent without justification** | Bouchard "Multi-agent is becoming the new overengineering" (Jan 2026, rev. Jul) https://www.louisbouchard.ai/agents-and-workflows/ ; KORE1 "defaulting to the most complex architecture"; single-agent-baseline research arXiv 2601.12307 | HM-quote / primary-doc |
| NEW: **cannot estimate cost** (within 30%) or has never dealt with a production failure | KORE1 | HM-quote/vendor |
| No baseline; improvement numbers with nothing to compare against | Bouchard; abbacus/learnist red-flag lists | HM-quote / vendor |
| Generic chatbot / "ChatGPT wrapper for [industry]"; about 70% of candidates have one | upskillist / eliteaiadvantage (vendor estimate) | vendor |
| Dead repo or demo; README doesn't run in a fresh environment | Bouchard | HM-quote |
| Notebooks only, stateless single calls, happy path only | HeroHunt; prior note | vendor |
| NEW: "vibe coding trap": cannot explain AI-generated code, or "the agent chose it" | Bouchard; HeroHunt; prior r/ExperiencedDevs anecdote | HM-quote / vendor / anecdote |
| NEW: **outdated product names** (e.g., "Vertex AI Agent Engine" in Oct 2026) | inferred from the Google rename | inference |
| NEW: **live demo with no spending caps**: "a single runaway script or malicious user can burn through thousands of dollars in API credits within hours" | https://oneuptime.com/blog/post/2026-01-30-llm-rate-limiting/view | vendor |
| Health-specific: sending personal health data to an LLM without saying so ("this MCP server passes your personal health data directly to the LLM") | https://github.com/MykalMachon/oura-mcp | anecdote |

---

## Ranked "skills to demonstrate" table

Evidence strength: **A** = several job-data sources plus hiring-manager support; **B** = job-data or primary-doc from one strong source; **C** = adoption, vendor, or inference only.

| Rank | Skill / artifact | Strength | Key sources |
|---|---|---|---|
| 1 | **Eval harness**: golden set (≥30–50 real cases), ≥2 approaches compared incl. a single-agent baseline, LLM-judge calibrated against your own labels, regression in CI | A | Skillenai LLM-eval +8.4%; HN evals 4–6%; Bouchard; KORE1; Google cert 22% domain |
| 2 | **MCP** (build a server *and* consume tools; publish to the registry) | A | GRFA 721; jobspipe 32,958; Skillenai 17.2% of Agentic AI Eng; HN 5%; HeroHunt green flag |
| 3 | **Cost/latency accounting** (per-run $ and p50/p95, model-choice tradeoff table) | A | Bouchard; KORE1 "within 30%"; HeroHunt; FDE loops |
| 4 | **Stateful orchestration with failure handling** (retries, checkpoints, HITL, stopping conditions) | A | Deloitte/Citi JDs; HeroHunt; KORE1; AiMi HN (prior note) |
| 5 | **Observability/tracing** (OpenTelemetry → Cloud Trace and/or Langfuse) plus a written finding from the traces | A− | jobspipe OTel 14,893; Skillenai observability 14,537; Citi JD; cert syllabus |
| 6 | **LangGraph** fluency (named in the most agent JDs) | A− (JD) | Skillenai 35.8–37.9%; GRFA 381; jobspipe 20,130 |
| 7 | **Google ADK + Agent Runtime + Memory Bank** | B | Citi JD; Google ADK roles; cert syllabus 33%; google-adk 10.1M/mo |
| 8 | **RAG with grounding/citations** (e.g., over health guidelines or your journal) | A− (volume) / weaker as a differentiator | GRFA 707; HN RAG flat 1–4% |
| 9 | **Deployment + live URL** with rate limits and spending caps; IaC; CI/CD | A (packaging) | prior note; Bouchard; cost-abuse source |
| 10 | **Security/guardrails/privacy** (PII handling, Model Armor/guardrails, OAuth scopes, read-only by construction) | B | cert 15% domain; Citi/Hitachi JDs; health domain |
| 11 | **A2A** (one real cross-agent boundary, not used everywhere) | C+ | Citi JD; cert syllabus; a2a-sdk 11.4M/mo; no index counts |
| 12 | **Durable execution (Temporal)** | C+ | jobspipe 3,236; KORE1 platform stack |
| 13 | Claude Agent SDK / OpenAI Agents SDK / Pydantic AI | C | high adoption (29.8M / 12.4M / 5.4M), thin JD evidence |
| 14 | AG-UI | C− | adoption only (7.4M); no JD evidence |
| — | Certification (Agentic Architect) | C for hiring weight, A as a syllabus | primary-doc; no HM guide cites certifications |

---

## Conflicts and uncertainties

- **Index disagreement:** GRFA ranks LangChain above LangGraph and MCP above both. Skillenai's agent-role buckets rank LangGraph above MCP. jobspipe ranks MCP above LangGraph. The universes differ (frontier companies + F500 vs. all indexed vs. company-confirmed). The direction is consistent; the exact ranks are not.
- **ADK demand is not measured** by any index I found. The case for it rests on one strong JD (Citi), Google's own hiring, the certification, and downloads. ADK is weaker than LangGraph as a JD keyword and stronger as a GCP-ecosystem signal.
- **Prior note correction:** GRFA's MCP count went from 624 to 721 and its roles from 2,376 to 2,664 (it is a weekly snapshot). The prior note's "MCP in 15.6% of Agentic AI Engineer postings" is now **17.2%** (Skillenai, 15 Oct).
- **Cloud demand ranking depends on the measure:** generic cloud mentions (AWS ≫ Azure > GCP) vs. GenAI platforms (roughly a tie). HN startups rarely name any of them.
- **A2A governance dates conflict** (LF in Jun 2025 vs. AAIF in Aug 2026).
- **Hiring-manager evidence is thin and much of it is commercial.** Bouchard is the only first-person hiring source re-verified this cycle. KORE1 and HeroHunt are recruiters or vendors. Interview-loop guides are prep sellers. Search turned up no named 2026 hiring-manager posts from engineers at labs beyond those in the prior note.
- **Eval set size**: 10 (Bouchard) vs. 30–50 (vendor) vs. 500 (KORE1 sample JD). Context decides: portfolio vs. production claim.
- **Demo video**: evidence is indirect (an FDE take-home requires a walkthrough recording). There is still no direct hiring-manager ranking of video vs. live URL.
- **Download numbers** are inflated by CI and transitive dependencies. They are not demand.
- The Google job pages could not be fetched in full (JS-rendered), so their details come from search snippets.

---

## Implications for this project (Google Health multi-agent system on GCP)

1. **Make the eval report the main artifact.** Build a golden set of real questions about your own data (e.g., "Did my HRV drop in the week after poor sleep?") with ground truth computed in SQL/pandas. Score answer correctness, numeric faithfulness, tool-trajectory accuracy (ADK evalset), and a calibrated LLM judge. Run it in CI. This one artifact covers skills #1, #3, and #5.
2. **Earn the multi-agent label with numbers.** Run a **single-agent + tools baseline** and the multi-agent design (patterned on Google's Personal Health Agent: Data Science / Domain Expert / Coach roles) on the same eval set, with cost, latency, and quality reported side by side. If multi-agent loses on some task types, say so in the README. That defuses the overengineering objection and shows judgment.
3. **Stack choice (balancing hiring keywords against GCP):** ADK on **Agent Runtime** (current naming), Memory Bank for journal/longitudinal memory, an MCP server wrapping the read-only Google Health API (publish it to the MCP registry so others can use it; this is a HeroHunt green flag), and OpenTelemetry → Cloud Trace (optionally Langfuse). To also hit the top JD keyword, consider **implementing one subgraph or a comparison variant in LangGraph**, or at least documenting how the design maps onto LangGraph. Use A2A at **one** real boundary only (e.g., exposing the coach agent to an external client), not throughout. Leave out AG-UI and Temporal unless needed (low JD evidence). If you need durability, document checkpoint/retry semantics instead.
4. **Live demo, safely:** a public demo should run on a **frozen, de-identified or synthetic snapshot** of your data with per-IP rate limits, token caps, and a billing alert. The real-data mode stays private. State the privacy model in the README ("read-only by construction"; what goes to the LLM). Add a 3–5 minute walkthrough video as a backup when the live demo is down.
5. **Publish the numbers:** a README results table (accuracy vs. baseline, $/query, p50/p95 latency), a failure-mode catalog from traces (e.g., "X% of runs looped on tool Y; fixed by Z"), and a 300–800 word retro or blog post. Add honest n-of-1 statistics caveats (autocorrelation, confounders). Data-science rigor is uncommon in this niche and directly relevant to health AI.
6. **Certification:** treat the **Professional Agentic Architect** exam guide as a build checklist. If you want to sit it after GA (mid-Nov 2026, $200, 1-year validity), take it *after* the project, which counts as the "1+ year building agentic solutions" practice. Skip Generative AI Leader. Don't present any certification as the headline.
7. **Use current names everywhere** (Gemini Enterprise Agent Platform, Agent Runtime, Agent Search). Pin dependency versions and set a quarterly refresh, so the repo doesn't read like "framework knowledge from a past cycle".
