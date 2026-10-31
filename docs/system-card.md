# System card: Calibrated Health Agent

A one-person portfolio project. This card says what the system is for, what it isn't for,
how it was evaluated, and where it falls short. It follows the shape of published model and
system cards, scaled to a single-user tool.

## What it is

An agent that answers one person's questions about their own wearable and journal data
(Fitbit / Pixel Watch via the Google Health API, plus a daily Google Form). Every number it
states comes from SQL or sandboxed Python it actually ran, with a re-runnable receipt. A
second part, the **forecast ledger**, locks daily predictions of the owner's mood, energy and
soreness before the outcome exists, then scores them against simple baselines.

Built on Google ADK 2.12 (graph `Workflow`) with Gemini 3.5 Flash-Lite on Vertex AI. It runs on
the owner's laptop (`cha ask` / `cha chat`) and in a scale-to-zero Cloud Run job.

## Intended use

- The owner asking about their own data: "how did I sleep this week", "compare my resting
  heart rate with last month", "what is missing".
- Reading the investigator's notes on its own forecast misses.
- A worked example of evaluation, security and observability practice for an agent that
  handles sensitive personal data.

## Out of scope

- **Medical advice, diagnosis or treatment.** The agent refuses to diagnose and sends red
  flags (chest pain, fainting, sudden breathlessness) to a clinician. It is not a medical
  device.
- **Anyone other than the owner.** There is no multi-user isolation and no sign-up.
- **Replacing a commercial health product.** This is a portfolio project, not an alternative
  to any vendor's service.
- **Decisions about medication, dosing or emergencies.**

## Health framing

The intended use matches what the US FDA describes as a **general wellness** product: it
describes the user's own data and supports healthy habits, without claims about any disease
or condition (FDA, *General Wellness: Policy for Low Risk Devices*). Under the **EU AI Act**,
Article 50 requires that people know when they are interacting with an AI system. Every
interface says the answers come from an AI agent and can be wrong, and the agent never
presents itself as a person or a clinician. This is a description of design intent, not legal
advice.

## Data

- **Real data stays in the owner's Google Cloud project** (a private bucket) and on the
  owner's laptop. It goes only to Vertex AI in that project.
- **Evals and CI use synthetic data only.** They run on a fixture built in code, on a
  free-tier key, with real-data runs refused (`CHA_DATA_MODE=synthetic`). Owner-labelled
  real transcripts stay in the git-ignored `data/evals/`.
- **Logs and traces carry counts, ids, hashes, durations and cost**, never health values,
  prompts or replies (trace content is forced off in the cloud, ADR 0006).
- **Public outputs** are aggregates and hashes: the ledger's chain hashes and a rounded
  scoreboard, never daily values.

## Safety and security controls

| Risk | Control |
|---|---|
| Made-up numbers | Every number must come from a tool result this turn. A verify node retries once, then adds a quiet note naming any figure not computed by a tool. Receipts re-run on demand (ADR 0003). |
| Prompt injection via journal notes, device names or code output | Untrusted text reaches the model only inside `<untrusted>` wrappers. SQL returns those columns as NULL. Red-team canaries measure success. |
| Data exfiltration | No tool can send data anywhere. The sandbox blocks network, processes and file writes (ADR 0004). |
| Destructive or blinded queries | Read-only SQLite behind an authorizer; the forecast ledger tables are refused. |
| Memory poisoning | Saving a memory needs the owner's explicit yes. |
| Runaway cost | Monthly dollar caps in code ($0.30 cloud agent, $0.30 chat), sandbox CPU and time limits, billing alerts. |

Full analysis: `docs/threat-model.md` (lethal trifecta, OWASP LLM 2025 and Agentic 2026
mapping, residual risks).

## Evaluation summary

Method: `docs/evals/methodology.md`. Numbers come from the latest file in
`docs/evals/results/`, each with its n, a Wilson 95% interval and the commit. Until the first
full run lands they are marked pending. They are never estimated.

- **Regression (gating):** 43 cases, 29 must-pass, run on every pull request.
- **Capability, safety, red team:** 74 / 30 / 39 cases, tracked nightly on a rotating slice.
- **Ablation:** no tools vs no code vs full vs multi-agent, paired by case with exact McNemar
  and minimum detectable difference.
- **Judges:** gate only after calibration against owner labels (TPR and TNR ≥ 0.8).

Phase 3 exit check, by reading: single agent 10/10, multi-agent 7/10 on the smoke questions.
The single agent stays the default until the ablation says otherwise (ADR 0005).

## Limitations

- **One person, small n.** Every rate has a wide interval, and the forecasting results need
  weeks of journaling before any comparison is reported (10 paired days minimum).
- **Synthetic evals are not real life.** The fixture covers known failure modes; owner
  labelling of real transcripts (kept private) is how new ones are found.
- **Lexicon graders under-count.** The first CI run showed escalation and gap phrasings the
  lexicons missed (since fixed). Judges cover the rest once calibrated.
- **Model drift.** A Gemini version change is a new forecaster in the ledger and needs a
  fresh eval baseline.
- **The laptop sandbox is defence in depth, not a VM.** Windows has no memory limit for it.
- **The agent can be wrong.** That's why it keeps score and shows receipts.

## Contact

Owner: Karthick Balaje Gopalakrishnan Elango ([kb2326](https://github.com/kb2326)).
