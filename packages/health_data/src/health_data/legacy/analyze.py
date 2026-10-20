"""Analysis loop — Phase 2, loop #2.

Iterates tracked metrics, scores today's value against a rolling baseline
(mean/std over the prior N days), and classifies severity. Default mode
completes a full pass so the digest has a complete picture (like an ADK
LoopAgent running to max_iterations). --fast-triage mode instead escalates
and stops at the FIRST alert-level anomaly — the early-exit analogue of
ADK's escalate=True, useful when you just want "is anything wrong right now"
without waiting on a full pass.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from statistics import mean, pstdev

import yaml
from health_core.settings import get_settings

from health_data import db

CONFIG = yaml.safe_load((get_settings().config_dir / "health.yaml").read_text())
A = CONFIG["analysis"]

# Below this standard deviation a baseline is treated as having no scale,
# rather than dividing by an epsilon and manufacturing a huge z-score.
MIN_SIGMA = 1e-6


def _history(conn, data_type: str, before: str, days: int) -> list[float]:
    rows = conn.execute(
        """SELECT agg_value FROM daily_metrics
           WHERE data_type=? AND date < ? ORDER BY date DESC LIMIT ?""",
        (data_type, before, days),
    ).fetchall()
    return [r[0] for r in rows]


def _severity(z: float | None, weight: float = 1.0) -> str:
    """Classify a z-score against thresholds scaled by learned reliability.

    `weight` comes from learn.py: above 1.0 when this signal has actually
    predicted the user's subjective state, below when it hasn't. Dividing
    the threshold by it means a signal that works for this person is heard
    sooner, and one that never works has to shout louder. This is the only
    place a learned parameter changes what the system does.
    """
    if z is None:
        return "insufficient_data"
    az = abs(z)
    if az >= A["alert_z"] / weight:
        return "alert"
    if az >= A["watch_z"] / weight:
        return "watch"
    return "normal"


def _signal_weight(conn, data_type: str) -> float:
    """Learned reliability for a signal; 1.0 (neutral) until proven otherwise."""
    try:
        row = conn.execute(
            "SELECT AVG(weight) FROM signal_weights WHERE signal=? AND n_scored >= 5",
            (data_type,),
        ).fetchone()
    except Exception:
        return 1.0
    return row[0] if row and row[0] else 1.0


def _last_complete_day(conn) -> str:
    """The most recent day whose data is finished being written.

    Scoring the current date is wrong: a day in progress has only a few
    hours of steps and calories in it, so a partial day reliably reads as a
    large negative anomaly. Yesterday is the newest day the wearable has
    actually finished reporting.
    """
    return (date.today() - timedelta(days=1)).isoformat()


# Which journal field each signal is expected to move, and which way. The
# lag is 1 because published work finds sleep and resting HRV predict the
# *following* day's state more consistently than they reflect the previous
# one — so the honest claim is forward-looking.
PREDICTIVE_SIGNALS = {
    "heart-rate-variability": [("energy", 1), ("mood", 1)],
    "daily-resting-heart-rate": [("energy", 1)],
    "sleep": [("energy", 1), ("mood", 1)],
    "exercise": [("soreness", 1)],
    "active-minutes": [("soreness", 1)],
}

# Signals where a *high* reading predicts a *low* subjective score, and
# vice versa. Elevated resting heart rate means worse recovery; hard
# training means more soreness, not less.
INVERTED = {"daily-resting-heart-rate"}
SORENESS_LIKE = {"soreness"}


def _emit_predictions(conn, day: str, data_type: str, z: float) -> None:
    """Turn an anomaly into dated, falsifiable claims about tomorrow.

    This is what makes the loop learnable: a flagged signal stops being a
    passive observation and becomes a prediction the next journal entry can
    score. Without this, nothing the analyser says is ever checked.
    """
    from datetime import date as _date

    targets = PREDICTIVE_SIGNALS.get(data_type)
    if not targets:
        return
    for target, lag in targets:
        high = z > 0
        if data_type in INVERTED:
            high = not high
        # A high sleep/HRV reading predicts high energy; for soreness the
        # relationship runs the other way — more exertion, more soreness.
        direction = ("high" if high else "low")
        if target in SORENESS_LIKE:
            direction = "high" if z > 0 else "low"
        target_date = (_date.fromisoformat(day) + timedelta(days=lag)).isoformat()
        conn.execute(
            """INSERT INTO predictions
               (made_on, signal, signal_date, signal_z, target, target_date,
                lag_days, expected_direction)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(signal, signal_date, target, lag_days) DO UPDATE SET
                 signal_z=excluded.signal_z, expected_direction=excluded.expected_direction""",
            (db.now_iso()[:10], data_type, day, z, target, target_date, lag, direction),
        )


def run(target_date: str | None = None, fast_triage: bool = False) -> dict:
    db.init_db()
    results = {}
    with db.connect() as conn:
        day = target_date or _last_complete_day(conn)
        # An anomaly is a claim about a (date, data_type). Re-analysing that
        # pair supersedes the previous claim entirely, so retract first and
        # re-assert below only if it still holds. Doing this before the
        # insufficient_data / no_variance early-exits matters: those are
        # exactly the paths a corrected day takes, and they used to leave the
        # old alert standing.
        conn.execute("DELETE FROM anomalies WHERE date=?", (day,))

        # Orchestration-graph handoff: read what ingest reported rather than
        # re-deriving it. A type whose sync failed has stale data, so scoring
        # it would produce a finding about the outage rather than the person.
        ingest = db.read_stage_output("ingest", db.now_iso()[:10]) or {}
        failed = {t for t, s in ingest.items() if isinstance(s, dict) and "error" in s}
        if failed:
            results["_skipped_failed_ingest"] = sorted(failed)

        for data_type in CONFIG["data_types"]:  # the loop
            if data_type in failed:
                results[data_type] = {"severity": "stale_ingest"}
                continue
            today_row = conn.execute(
                "SELECT agg_value FROM daily_metrics WHERE data_type=? AND date=?",
                (data_type, day),
            ).fetchone()
            hist = _history(conn, data_type, day, A["min_history_days"] * 4)
            if not today_row or len(hist) < A["min_history_days"]:
                results[data_type] = {"severity": "insufficient_data"}
                continue

            value = today_row[0]
            mu, sigma = mean(hist), pstdev(hist)
            # A flat baseline has no scale to measure deviation against.
            # Dividing by a 1e-9 floor instead would turn every reading into
            # a z of ~1e9, i.e. a permanent alert on the most stable metrics.
            if sigma < MIN_SIGMA:
                results[data_type] = {
                    "value": value, "baseline_mean": mu, "baseline_std": sigma,
                    "z_score": None, "severity": "no_variance",
                }
                continue
            z = (value - mu) / sigma
            weight = _signal_weight(conn, data_type)
            severity = _severity(z, weight)
            results[data_type] = {
                "value": value, "baseline_mean": mu, "baseline_std": sigma,
                "z_score": z, "severity": severity, "signal_weight": round(weight, 3),
            }

            if severity in ("watch", "alert"):
                _emit_predictions(conn, day, data_type, z)
                conn.execute(
                    """INSERT INTO anomalies
                       (date, data_type, value, baseline_mean, baseline_std, z_score, severity, detected_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(date, data_type) DO UPDATE SET
                         value=excluded.value, baseline_mean=excluded.baseline_mean,
                         baseline_std=excluded.baseline_std, z_score=excluded.z_score,
                         severity=excluded.severity, detected_at=excluded.detected_at""",
                    (day, data_type, value, mu, sigma, z, severity, db.now_iso()),
                )

            if fast_triage and severity == "alert":
                results["_early_exit"] = f"stopped after {data_type} (alert-level anomaly)"
                break  # early exit — the escalate=True analogue

    db.write_stage_output("analyze", day, results)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    parser.add_argument("--fast-triage", action="store_true")
    args = parser.parse_args()
    out = run(args.date, args.fast_triage)
    for dtype, r in out.items():
        if dtype == "_early_exit":
            print(f"\n{r}")
            continue
        sev = r["severity"]
        if r.get("z_score") is None:
            print(f"{dtype:30s} {sev}")
        else:
            print(f"{dtype:30s} {sev:8s} value={r['value']:.1f} z={r['z_score']:+.2f}")
