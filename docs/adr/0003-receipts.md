# ADR 0003: Every number has a receipt

**Status:** accepted (built in Phase 3, evaluated in Phase 4), 2026-10-30

## Context

LLMs state plausible numbers they never computed. In Google's PHIA study, a plain LLM answered
personal-health data questions correctly about 22% of the time, and an agent that wrote and
ran code reached 84%. For a health agent, a confident wrong number is the main failure mode.

## Decision

- Numbers come only from `run_sql` (read-only SQLite behind an authorizer) or `run_python`
  (the sandbox, ADR 0004). Each call stores a **receipt**: the code, a hash of the data it
  read, the as-of date, the output and the executor. The answer cites the receipt id next to
  the number.
- A deterministic **verify node** checks every number in the draft against this turn's tool
  outputs, at the answer's own precision. Dates, list markers, scales and the question's own
  numbers are skipped. A draft with unbacked numbers is sent back once with feedback. If it
  still has them, the answer is returned with an `unverified: …` footer, never passed off as
  checked.
- `cha receipt <id> --rerun` re-executes any receipt and says whether the value still holds,
  or whether the data changed underneath it (late sync or backfill).

## Consequences

- Evals can grade truth mechanically. `numbers` compares against truth SQL, `receipts_rerun`
  re-runs every cited receipt, and `no_unverified` fails any footer.
- Formatting can trip the verifier. The first CI run found day lists ("October 9, 10, 11, 12,
  and 13") read as numbers. Fixed: a list closed by "and"/"or", or a range, after a month
  counts as dates; a count after a date is still checked.
- Unit conversions must happen inside the code ("convert minutes to hours inside the query").
  Otherwise "5 hours 36 minutes" has no receipt.
