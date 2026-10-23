"""Settle locked days: score them, void them, or record that no outcome came.

For each locked day D without a settlement entry in the chain:

- its journal outcome (first valid submission, `journal_outcome`) was submitted after
  D's lock: every non-abstained (forecaster, target) is scored (RPS and log score) and an
  `outcome` entry seals the submission's row hash and the scores;
- the outcome was submitted at or before the lock: the day is void, because the bets
  were made when the answer already existed;
- no outcome and it is past D+1 06:00 owner time: a `no_outcome` entry;
- otherwise the day stays open for a later run.

One transaction per day; re-running settles nothing twice.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, time, timedelta

from health_data import civil, db

from health_ledger import chain, dist, features

TARGETS = ("mood", "energy", "soreness")
SETTLED = ("outcome", "void", "no_outcome")
OUTCOME_DEADLINE = time(6, 0)  # on D+1, owner time


def _open_days(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    return list(conn.execute(
        f"""SELECT s.day, s.locked_at FROM snapshots s
            WHERE NOT EXISTS (SELECT 1 FROM ledger l WHERE l.day = s.day
                              AND l.kind IN ({",".join("?" * len(SETTLED))}))
            ORDER BY s.day""", SETTLED))


def _score(conn: sqlite3.Connection, day: str, outcome: dict[str, int], scored_at: str) -> list[tuple]:
    rows = []
    for forecaster, target, probs_json in conn.execute(
            "SELECT forecaster, target, probs_json FROM forecasts "
            "WHERE day = ? AND probs_json IS NOT NULL ORDER BY forecaster, target", (day,)):
        p = dist.normalize(json.loads(probs_json))
        y = outcome[target]
        rows.append((day, forecaster, target, y, dist.rps(p, y), dist.log_score(p, y), scored_at))
    return rows


def settle(conn: sqlite3.Connection, now: datetime) -> dict[str, int]:
    counts = {"scored": 0, "voided": 0, "no_outcome": 0}
    stamp = db.utc_stamp(now)
    for day, locked_at in _open_days(conn):
        row = conn.execute(
            """SELECT o.mood, o.energy, o.soreness, s.submitted_at, s.row_hash
               FROM journal_outcome o JOIN journal_submissions s ON s.id = o.submission_id
               WHERE o.date = ?""", (day,)).fetchone()
        deadline = datetime.combine(datetime.fromisoformat(day).date() + timedelta(days=1),
                                    OUTCOME_DEADLINE, tzinfo=civil.zone())
        if conn.in_transaction:
            conn.commit()
        try:
            if row is not None and row[3] > locked_at:
                outcome: dict[str, int] = dict(zip(TARGETS, row[:3], strict=True))
                scores = _score(conn, day, outcome, stamp)
                conn.executemany(
                    """INSERT INTO scores (day, forecaster, target, outcome, rps, log_score,
                                           scored_at) VALUES (?, ?, ?, ?, ?, ?, ?)""", scores)
                chain.append(conn, day, "outcome", {
                    "outcome_row_hash": row[4],
                    "scores_hash": features.sha256(features.canonical([list(r) for r in scores])),
                })
                counts["scored"] += 1
            elif row is not None:
                chain.append(conn, day, "void", {"reason": "journal before lock"})
                counts["voided"] += 1
            elif now >= deadline:
                chain.append(conn, day, "no_outcome", {})
                counts["no_outcome"] += 1
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return counts
