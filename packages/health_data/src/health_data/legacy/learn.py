"""Learning loop — the fourth loop, and the one that closes the harness.

The other three loops are *processing* loops: data in, artefact out, no
change to how the system behaves next time. Run them a thousand times and
`watch_z: 1.5` is still a number a human guessed.

This loop is different. It reads predictions that `analyze.py` emitted,
scores them against the journal entries that have since arrived, and
updates a per-signal weight. Signals that predict *this* person get
promoted; signals that never do get demoted below the reporting threshold.

That is the write-manage-read cycle the harness literature describes,
applied to health signals. The journal is what makes it possible at all —
it is the only source of truth about subjective state that the wearable
cannot see, so it can independently score a claim the wearable data made.

Run:
    uv run python -m health_data.legacy.learn            # score matured predictions
    uv run python -m health_data.legacy.learn --report   # show current signal reliability
"""
from __future__ import annotations

import argparse
from datetime import date

import yaml
from health_core.settings import get_settings

from health_data import db, obs

log = obs.get_logger(__name__)

CONFIG = yaml.safe_load((get_settings().config_dir / "health.yaml").read_text())
JOURNAL_FIELDS = CONFIG["journal_fields"]

# A prediction is only meaningful if the journal itself varies. Scoring
# against a flat journal would credit a signal for predicting a constant.
MIN_JOURNAL_SPREAD = 1.0

# How far a weight may move from neutral. Bounded so one lucky week cannot
# silence a signal outright, and an unlucky one cannot amplify noise.
WEIGHT_FLOOR, WEIGHT_CEILING = 0.5, 1.5

# Below this many scored predictions a hit rate is not evidence of anything.
MIN_SCORED_FOR_WEIGHT = 5


def _journal_baseline(conn, field: str, before: str, days: int = 28) -> tuple[float, float] | None:
    """(mean, spread) for a journal field over its recent history."""
    rows = conn.execute(
        f"""SELECT {field} AS v FROM journal
            WHERE date < ? AND {field} IS NOT NULL
            ORDER BY date DESC LIMIT ?""",
        (before, days),
    ).fetchall()
    values = [r[0] for r in rows]
    if len(values) < 3:
        return None
    mean = sum(values) / len(values)
    spread = max(values) - min(values)
    return mean, spread


def score_pending(conn, today: str | None = None) -> dict:
    """Score every prediction whose target date has arrived and been logged."""
    today = today or date.today().isoformat()
    pending = conn.execute(
        """SELECT id, signal, target, target_date, lag_days, expected_direction
           FROM predictions WHERE hit IS NULL AND target_date < ?""",
        (today,),
    ).fetchall()

    scored = skipped = 0
    for pid, _, target, target_date, _, direction in pending:
        if target not in JOURNAL_FIELDS:
            continue
        row = conn.execute(
            f"SELECT {target} FROM journal WHERE date = ?", (target_date,)
        ).fetchone()
        if row is None or row[0] is None:
            # No journal entry for that day. Not a miss — an unanswered
            # question. Leave it pending; it may never be scorable, which
            # is itself honest.
            skipped += 1
            continue
        baseline = _journal_baseline(conn, target, target_date)
        if baseline is None or baseline[1] < MIN_JOURNAL_SPREAD:
            skipped += 1
            continue
        mean, _ = baseline
        actual = row[0]
        hit = int((actual < mean) if direction == "low" else (actual > mean))
        conn.execute(
            "UPDATE predictions SET actual_value=?, hit=?, scored_at=? WHERE id=?",
            (actual, hit, db.now_iso(), pid),
        )
        scored += 1

    return {"scored": scored, "skipped_no_journal": skipped, "pending": len(pending)}


def recompute_weights(conn) -> list[dict]:
    """Rebuild per-signal weights from every scored prediction."""
    rows = conn.execute(
        """SELECT signal, target, lag_days,
                  COUNT(*) AS n, SUM(hit) AS hits
           FROM predictions WHERE hit IS NOT NULL
           GROUP BY signal, target, lag_days"""
    ).fetchall()

    out = []
    for signal, target, lag, n, hits in rows:
        hit_rate = hits / n if n else None
        # Chance is 0.5. Move the weight proportionally to the distance from
        # chance, but only once there is enough evidence to justify moving.
        if n >= MIN_SCORED_FOR_WEIGHT and hit_rate is not None:
            weight = 1.0 + (hit_rate - 0.5)
            weight = max(WEIGHT_FLOOR, min(WEIGHT_CEILING, weight))
        else:
            weight = 1.0
        conn.execute(
            """INSERT INTO signal_weights
               (signal, target, lag_days, n_scored, n_hit, hit_rate, weight, updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(signal, target, lag_days) DO UPDATE SET
                 n_scored=excluded.n_scored, n_hit=excluded.n_hit,
                 hit_rate=excluded.hit_rate, weight=excluded.weight,
                 updated_at=excluded.updated_at""",
            (signal, target, lag, n, hits, hit_rate, weight, db.now_iso()),
        )
        out.append({
            "signal": signal, "target": target, "lag_days": lag,
            "n_scored": n, "hit_rate": round(hit_rate, 3) if hit_rate is not None else None,
            "weight": round(weight, 3),
        })
    return out


def effective_threshold(conn, signal: str, base_z: float) -> float:
    """The z-threshold for `signal`, adjusted by what it has actually predicted.

    A signal that predicts well for this person gets a *lower* bar (we want
    to hear from it sooner); one that never predicts gets a higher bar. This
    is the point where the learned weight feeds back into detection.
    """
    row = conn.execute(
        """SELECT AVG(weight) FROM signal_weights
           WHERE signal=? AND n_scored >= ?""",
        (signal, MIN_SCORED_FOR_WEIGHT),
    ).fetchone()
    weight = row[0] if row and row[0] else 1.0
    return base_z / weight


def run(today: str | None = None) -> dict:
    db.init_db()
    with db.connect() as conn:
        scoring = score_pending(conn, today)
        weights = recompute_weights(conn)
        conn.commit()
    result = {**scoring, "signals": weights}
    db.write_stage_output("learn", today or date.today().isoformat(), result)
    log.info("learn ok", extra={"attrs": {"span": "learn", **scoring, "n_signals": len(weights)}})
    return result


def _report() -> None:
    db.init_db()
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT signal, target, lag_days, n_scored, n_hit, hit_rate, weight
               FROM signal_weights ORDER BY COALESCE(hit_rate, -1) DESC"""
        ).fetchall()
        pend = conn.execute(
            "SELECT COUNT(*) FROM predictions WHERE hit IS NULL"
        ).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
    print(f"predictions: {total} total, {pend} awaiting a journal entry\n")
    if not rows:
        print("No signal has been scored yet.")
        print("The loop needs an anomaly, then a journal entry for the day after it.")
        return
    print(f"{'SIGNAL':26} {'TARGET':9} {'LAG':>3} {'N':>4} {'HIT RATE':>9} {'WEIGHT':>7}")
    print("-" * 64)
    for s, t, lag, n, _, hr, w in rows:
        hr_s = f"{hr:.0%}" if hr is not None else "--"
        print(f"{s:26} {t:9} {lag:>3} {n:>4} {hr_s:>9} {w:>7.2f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--report", action="store_true", help="show signal reliability and exit")
    p.add_argument("--date", default=None)
    args = p.parse_args()
    if args.report:
        _report()
    else:
        out = run(args.date)
        print(f"scored {out['scored']} prediction(s); "
              f"{out['skipped_no_journal']} still awaiting a journal entry")
        for s in out["signals"]:
            hr = f"{s['hit_rate']:.0%}" if s["hit_rate"] is not None else "--"
            print(f"  {s['signal']:26} -> {s['target']:9} lag {s['lag_days']}  "
                  f"n={s['n_scored']:<3} hit={hr:>5}  weight={s['weight']}")
