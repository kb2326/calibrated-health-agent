# Phase 4.5: a capable agent (design)

Status: direction approved by the owner 2026-10-31 ("go ahead with phase 4.5"). The data-layer
details in §5 are finalised from `docs/research/11-google-health-api-catalog.md`.
Merges together with Phase 4, before Phase 5 (web front end).

## 1. Why

The owner labelled 110 answers (`data/evals/label-set-{1,2}.labels.jsonl`): 32 failed. Error
analysis found five root causes:

1. **Multi-agent pipeline broken.** The verify retry went to the synthesizer, which has no tools.
   It gave up ("I cannot verify"), printed tool calls as text, and invented a tool name. It
   failed 14 of 30.
2. **Number check too strict.** It flags window lengths ("30" in "last 30 days" for "last month")
   and writes an alarming `unverified:` footer on correct answers.
3. **Over-caution.** "Should I do a hard workout today?" got "I'm not a clinician, consult a
   professional". Safety suite: 70%.
4. **Thin view of the data.** Every type is flattened to one number a day. Sleep stages,
   workouts, zones and minute-level SpO2 (12k points) are invisible. The synthetic fixture has
   only 4 metrics, so about 25 failures were "no data" answers on SpO2, skin temperature and
   VO2 max.
5. **No weather.**

All 20 real-data answers passed, so the agent is sound at its core. Its rigidity comes from
the design around it.

Owner's direction: "make sure the agents are architected in a standard manner with current
trends and proven architectures, not old-school rigidness."

## 2. Goals

1. Answer natural questions over **all** the owner's data, including detail (stages,
   sessions, zones, intraday) and weather. With partial data, compute on what exists and say
   what's missing; never refuse because a day is missing.
2. **Modern, proven agent architecture** (§4), with each choice justified by a published
   pattern.
3. Keep the guarantees: every number computed by code with a receipt, read-only data,
   untrusted text wrapped, no exfiltration path, no diagnosis, red flags escalated.
4. **Measurably better:** on the owner's 110 labelled questions, fewer failures. The safety
   suite improves without the red team getting worse. Same CI gate.
5. Weather for **Erode** (home city) by default. The web front end (Phase 5) passes the
   device's **live location**.

## 3. Non-goals

- New write access to any source; medical claims; a different model family; MCP.
- Rebuilding the forecast ledger (its pre-registered plan is frozen; it only gains nothing).

## 4. Architecture (decided)

```
question ─► screen (code) ─► Health agent (Gemini, thinking on, ReAct tool loop)
                               │ tools: data_catalog · query_metric · run_sql · run_python
                               │        weather · journal · memory · scoreboard
                               │ agents-as-tools (optional): coach · domain_expert
                               ▼
                        grounding check (code) ─► answer (+ quiet note if a number is unbacked)
                               └─ one revision, back to the same agent, with its tools
```

1. **One capable agent in a tool loop (ReAct).** This is the pattern recommended by Anthropic
   ("Building effective agents"), Google ADK and OpenAI's agent guide for open-ended Q&A:
   start with a single agent with good tools, and add agents only where they measurably help.
2. **Thinking on (built-in planner).** Gemini's native thinking with a small budget, so the
   agent plans the computation before acting. It's ADK's `BuiltInPlanner`, and the cost stays
   inside the cap.
3. **Context engineering, just in time.** A `data_catalog` tool returns every metric and
   table with its meaning, unit, granularity, date range, days covered and gaps (a semantic
   layer). The agent discovers what exists instead of reading a fixed list baked into the
   prompt.
4. **Code as the main analysis tool (code-act).** `run_python` gets a richer bundle (all daily
   metrics, detail tables, journal, weather) as pandas frames. `run_sql` covers every table.
   A new `query_metric(metric, start, end, agg)` handles common reads without SQL.
5. **Agents as tools, not a fixed pipeline.** The rigid router → specialists → synthesizer
   graph is replaced by ADK `AgentTool` specialists (coach, domain expert) that the main agent
   *may call*: Anthropic's orchestrator-workers pattern. The verify retry always returns to an
   agent that has tools. The ablation keeps comparing "with specialists" against "without",
   and the default follows the result (ADR 0005).
6. **Guardrails as layers, not refusals.**
   - Deterministic screen and grounding check in code.
   - Policy in the instructions: helpful-first wellness guidance; never diagnose; escalate
     red flags.
   - Evals and red team in CI.

   Refusal is reserved for diagnosis, dosing and unsafe asks.
7. **Smarter grounding check.** Numbers implied by the question or by dates are treated as
   backed: windows ("last month" → 30 or 31 days), day counts between stated dates, years,
   list markers, scales. A truly unbacked number gets one revision. If it's still unbacked, a
   quiet note ("1 figure wasn't computed: …"), not a footer that reads like an error.
8. **Trusted context, not model-chosen arguments, for location.** The weather tool takes no
   free-text location from the model. It reads coordinates from the session context: the
   front end's live location in Phase 5, otherwise Erode (11.34 N, 77.72 E). This keeps the
   "no way to send data out" guarantee: the only outbound call carries coordinates the user
   supplied, and dates.

## 5. Data layer

- **Detail tables derived from `raw_points.raw_json`** (no new downloads):
  - `sleep_sessions` (start, end, minutes per stage: deep / light / REM / awake, efficiency);
  - `exercise_sessions` (type, start, duration, distance, calories, average and maximum heart
    rate);
  - `hr_zone_minutes` (day, zone, minutes);
  - `spo2_nightly` (day, average, minimum, minutes below 90%).

  These are rebuilt idempotently by the sync job and by `cha-data db derive`.
- **New API types and fields** from the catalogue (§11 research), within the existing
  read-only scopes. A new scope needs the owner's re-consent and is listed separately.
- **Weather:** a `weather_daily` table (date, temperature min/max/mean, humidity, precipitation,
  UV, sunrise/sunset), backfilled from the Open-Meteo archive and kept current by the nightly
  job for the home location. The live `weather` tool covers the forecast and other places
  (Phase 5 live location). Open-Meteo is free with no key; attribution goes in the README.
- `data_catalog` and the SQL authorizer allow the new tables (read-only, not blinded).

## 6. Synthetic fixture

The fixture is rebuilt to mirror the real schema: all synced types with realistic ranges and
gaps, plus sleep stages, sessions, zones, intraday SpO2 samples and weather. The eval cases
cover them. The owner's 110 questions are re-run on the new fixture and on real data.

## 7. Evals and acceptance

- **Re-run the 110 labelled questions** with the new agent. A blind pairwise judge plus the
  owner's spot check compares new against old, and the owner's failure notes become
  regression cases.
- **Suites:**
  - regression must-pass stays green;
  - safety improves from 70%;
  - red team does not get worse (90%);
  - new cases for stages, sessions, weather and partial-data comparisons.
- **Ablation:** with versus without specialists, and thinking on versus off.
- **CI gate:** unchanged mechanics.

## 8. Constraints

Same as Phase 4: under $1/month steady state (the owner allowed $2–3 for today's runs),
personal accounts, read-only data, no real data in the repo or CI, and the frozen ledger plan
untouched.

## 9. Left to the builder

Table and column names; how much thinking budget (start small); specialist instructions; the
weather variables beyond those listed; the catalogue's text format.
