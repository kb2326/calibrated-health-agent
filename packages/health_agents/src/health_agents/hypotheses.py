"""The investigator's hypotheses: tested when written, then judged on later days only.

A hypothesis is a claim about one target ("energy tends to be lower") under a condition
the morning lock could know, written as code: `def condition(days) -> boolean Series`,
evaluated in the sandbox over the lock-time columns only. So every hypothesis is usable
by forecaster 7 by construction, and an outcome column can't sneak into a condition.

`validate` checks a proposal (wording, a condition that runs, enough but not all days,
not a duplicate of a live one), records its in-sample evidence with receipts, and stores
it as `open`. `retest` re-evaluates every live hypothesis on days **settled after it was
created** and appends a status row by a fixed rule, so the agent never grades its own idea:

- `open` until at least 5 condition days and 5 other days exist out of sample;
- `supported` when the effect has the stated direction and p < 0.10;
- `refuted` when at least 10 condition days exist out of sample and it is not supported.

The owner can `retire` one; retired and refuted hypotheses are no longer live.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date

from health_data import db
from health_ledger.associations import mean_diff_permutation
from health_ledger.features import canonical, sha256
from health_ledger.forecasters.base import TARGETS

from . import bundle, receipts, sandbox

MIN_MATCHES = 3
MAX_SHARE = 0.8
DUPLICATE_JACCARD = 0.9
OOS_MIN = 5
OOS_REFUTE = 10
P_SUPPORT = 0.10
DISEASE_WORDS = ("diagnos", "disease", "disorder", "syndrome", "depress", "anxiety disorder",
                 "insomnia", "apnea", "diabetes", "hypertension", "infection", "covid")
NOT_LIVE = ("refuted", "retired")


@dataclass(frozen=True)
class Proposal:
    statement: str
    target: str
    direction: str
    condition_code: str


def _mask_code(condition_code: str, cols: list[str]) -> str:
    return (condition_code.rstrip() + f"\n\ncols = {cols!r}\n"
            "result = [bool(x) for x in condition(days[cols]).fillna(False).astype(bool).tolist()]\n")


def _scored_days(conn: sqlite3.Connection, as_of: date) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT day FROM ledger WHERE kind = 'outcome' AND day <= ?", (as_of.isoformat(),))}


def _evaluate(conn: sqlite3.Connection, condition_code: str, as_of: date
              ) -> tuple[dict[str, bool], list[dict], str, str] | str:
    """Mask per day, the days rows, the receipt id; or an error string."""
    data = bundle.build(conn, as_of, investigator=True)
    code = _mask_code(condition_code, bundle.lock_columns(conn))
    result = sandbox.run(code, data)
    days = data["frames"]["days"]
    if not result.ok:
        return f"condition failed: {result.error}"
    if not isinstance(result.result, list) or len(result.result) != len(days):
        return "condition must return one boolean per day"
    rid = receipts.record(conn, kind="python", code=code, data_hash=bundle.data_hash(data),
                          as_of=as_of.isoformat(), output=result.result,
                          executor=receipts.SANDBOX, context="investigator")
    mask = {row["day"]: bool(m) for row, m in zip(days, result.result, strict=True)}
    return mask, days, rid, code


def _split(mask: dict[str, bool], days: list[dict], target: str, keep: set[str]
           ) -> tuple[list[float], list[float]]:
    cond, other = [], []
    for row in days:
        if row["day"] in keep and row.get(target) is not None:
            (cond if mask.get(row["day"]) else other).append(float(row[target]))
    return cond, other


def _latest(conn: sqlite3.Connection) -> dict[str, str]:
    return {hid: status for hid, status in conn.execute(
        "SELECT hypothesis_id, status FROM hypothesis_status s WHERE id = "
        "(SELECT MAX(id) FROM hypothesis_status WHERE hypothesis_id = s.hypothesis_id)")}


def _wording_ok(statement: str) -> bool:
    lowered = statement.lower()
    return not any(word in lowered for word in DISEASE_WORDS)


def _clause(statement: str) -> str:
    text = re.sub(r"^\s*association[^:]*:\s*", "", statement.strip(), flags=re.I)
    return text[:200]


def validate(conn: sqlite3.Connection, proposal: Proposal, as_of: date
             ) -> tuple[str | None, str | None]:
    """Store a checked hypothesis; returns (id, None) or (None, reason). Does not commit."""
    if proposal.target not in TARGETS:
        return None, f"unknown target {proposal.target!r}"
    if proposal.direction not in ("lower", "higher"):
        return None, "direction must be 'lower' or 'higher'"
    if not _wording_ok(proposal.statement):
        return None, "wording: no disease or diagnosis words"
    hid = "h-" + sha256(f"{proposal.target}|{proposal.direction}|{proposal.condition_code}")[:10]
    if conn.execute("SELECT 1 FROM hypotheses WHERE id = ?", (hid,)).fetchone():
        return None, "duplicate of an existing hypothesis"
    evaluated = _evaluate(conn, proposal.condition_code, as_of)
    if isinstance(evaluated, str):
        return None, evaluated
    mask, days, rid, _ = evaluated
    scored = _scored_days(conn, as_of)
    cond, other = _split(mask, days, proposal.target, scored)
    n_scored = len(cond) + len(other)
    if len(cond) < MIN_MATCHES:
        return None, f"too few matching scored days ({len(cond)})"
    if n_scored and len(cond) > MAX_SHARE * n_scored:
        return None, "too many matching days to tell anything apart"
    mine = {d for d, m in mask.items() if m and d in scored}
    latest = _latest(conn)
    for other_id, code in conn.execute(
            "SELECT id, condition_code FROM hypotheses WHERE target = ?", (proposal.target,)):
        if latest.get(other_id) in NOT_LIVE:
            continue
        theirs = _evaluate(conn, code, as_of)
        if isinstance(theirs, str):
            continue
        their_days = {d for d, m in theirs[0].items() if m and d in scored}
        union = mine | their_days
        if union and len(mine & their_days) / len(union) >= DUPLICATE_JACCARD:
            return None, f"duplicate of live hypothesis {other_id}"
    effect, p = mean_diff_permutation(cond, other) if other else (0.0, 1.0)
    statement = (f"Association (n={len(cond)}): {proposal.target} tends to be "
                 f"{proposal.direction} when {_clause(proposal.statement)}")
    in_sample = {"n_cond": len(cond), "n_other": len(other), "effect": round(effect, 4),
                 "p_value": round(p, 4), "as_of": as_of.isoformat()}
    conn.execute("INSERT INTO hypotheses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (hid, as_of.isoformat(), statement, proposal.target, proposal.direction,
                  proposal.condition_code, canonical(in_sample), json.dumps([rid]), db.utc_stamp()))
    _status(conn, hid, as_of.isoformat(), "open", len(cond), len(other), effect, p, rid)
    return hid, None


def _status(conn: sqlite3.Connection, hid: str, day: str, status: str, n_cond: int,
            n_other: int, effect: float | None, p: float | None, rid: str | None) -> None:
    conn.execute("INSERT OR IGNORE INTO hypothesis_status (hypothesis_id, day, status, n_cond,"
                 " n_other, effect, p_value, receipt_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                 (hid, day, status, n_cond, n_other, effect, p, rid, db.utc_stamp()))


def retest(conn: sqlite3.Connection, today: date) -> dict[str, int]:
    """Judge every live hypothesis on its out-of-sample days; one status row per settled day."""
    counts = {"tested": 0, "supported": 0, "refuted": 0}
    as_of = bundle.latest_settled_day(conn)
    if as_of is None:
        return counts
    latest = _latest(conn)
    done = {r[0] for r in conn.execute("SELECT hypothesis_id FROM hypothesis_status WHERE day = ?",
                                       (as_of.isoformat(),))}
    for hid, created_day, target, direction, code in conn.execute(
            "SELECT id, created_day, target, direction, condition_code FROM hypotheses").fetchall():
        if latest.get(hid) in NOT_LIVE or hid in done:
            continue
        evaluated = _evaluate(conn, code, as_of)
        if isinstance(evaluated, str):
            continue  # a condition that stops running stays as it was
        mask, days, rid, _ = evaluated
        later = {d for d in _scored_days(conn, as_of) if d > created_day}
        cond, other = _split(mask, days, target, later)
        effect, p = (mean_diff_permutation(cond, other) if cond and other else (None, None))
        status = "open"
        if len(cond) >= OOS_MIN and len(other) >= OOS_MIN and effect is not None and p is not None:
            right_way = effect < 0 if direction == "lower" else effect > 0
            if right_way and p < P_SUPPORT:
                status = "supported"
            elif len(cond) >= OOS_REFUTE:
                status = "refuted"
        _status(conn, hid, as_of.isoformat(), status, len(cond), len(other), effect, p, rid)
        counts["tested"] += 1
        if status in ("supported", "refuted"):
            counts[status] += 1
    return counts


def retire(conn: sqlite3.Connection, hid: str, day: date) -> bool:
    if not conn.execute("SELECT 1 FROM hypotheses WHERE id = ?", (hid,)).fetchone():
        return False
    conn.execute("INSERT INTO hypothesis_status (hypothesis_id, day, status, n_cond, n_other,"
                 " created_at) VALUES (?, ?, 'retired', 0, 0, ?) ON CONFLICT(hypothesis_id, day)"
                 " DO NOTHING", (hid, f"{day.isoformat()}~retired", db.utc_stamp()))
    return True


def live(conn: sqlite3.Connection, before: str | None = None) -> list[dict]:
    """Hypotheses not refuted or retired, created before `before` (an ISO timestamp):
    supported first, then open, newest first within each."""
    latest = conn.execute(
        "SELECT h.id, h.statement, h.target, h.direction, h.created_at, s.status, s.n_cond "
        "FROM hypotheses h JOIN hypothesis_status s ON s.hypothesis_id = h.id AND s.id = "
        "(SELECT MAX(id) FROM hypothesis_status WHERE hypothesis_id = h.id)").fetchall()
    rows = [{"id": i, "statement": st, "target": t, "direction": d, "created_at": c,
             "status": s, "n": n} for i, st, t, d, c, s, n in latest
            if s not in NOT_LIVE and (before is None or c < before)]
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    rows.sort(key=lambda r: 0 if r["status"] == "supported" else 1)
    return rows
