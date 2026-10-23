"""The public scoreboard: how every forecaster is doing, in aggregates with real n.

It never contains a day's value, a date of a scored day, a lock time or a missing-input
flag: only counts, mean scores, paired skill scores and calibration histograms. Skill vs a
reference is computed over the days both scored (paired), and says how many those were.
The primary endpoint (pre-registered, docs/ledger/analysis-plan.md) is energy RPS skill of
the Gemini forecaster vs persistence, with a block-bootstrap interval once 10 paired days
exist.
"""
from __future__ import annotations

import html
import json
import sqlite3
from collections import defaultdict

from health_data import db

from health_ledger import dist

TARGETS = ("mood", "energy", "soreness")
REFERENCES = ("climatology", "persistence")
PRIMARY_TARGET = "energy"
PRIMARY_MIN_N = 10
# Pinned to the forecaster 6 that the analysis plan pre-registered and that locked first;
# a later model change is a new forecaster and never moves the primary endpoint (M4).
PRIMARY_FORECASTER = "gemini:gemini-3.5-flash-lite"
NOTES_FORECASTER = "gemini_notes:gemini-3.5-flash-lite"
INTERVAL_NOTE = "95% interval: paired moving-block bootstrap, block 7, 2000 resamples"


def _paired(a: dict[str, float], b: dict[str, float]) -> tuple[list[float], list[float]]:
    days = sorted(set(a) & set(b))
    return [a[d] for d in days], [b[d] for d in days]


def _skill(scores: dict[str, float], ref: dict[str, float]) -> dict | None:
    mine, theirs = _paired(scores, ref)
    if not mine:
        return None
    return {"skill": dist.skill(sum(mine) / len(mine), sum(theirs) / len(theirs)), "n": len(mine)}


def _comparison(rps: dict, forecaster: str, reference: str, target: str) -> dict:
    mine, ref = _paired(rps.get((forecaster, target), {}), rps.get((reference, target), {}))
    out = {"target": target, "forecaster": forecaster, "reference": reference, "n": len(mine),
           "skill_vs_reference": None, "note": f"n below {PRIMARY_MIN_N}"}
    if len(mine) >= PRIMARY_MIN_N:
        out["skill_vs_reference"] = list(dist.block_bootstrap_skill(mine, ref))
        out["note"] = INTERVAL_NOTE
    return out


def build(conn: sqlite3.Connection) -> dict:
    rps: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    logs: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    calib: dict[tuple[str, str], list] = defaultdict(list)
    for day, forecaster, target, outcome, score, log_score, probs_json in conn.execute(
            """SELECT s.day, s.forecaster, s.target, s.outcome, s.rps, s.log_score, f.probs_json
               FROM scores s JOIN forecasts f USING (day, forecaster, target)
               ORDER BY s.day, s.forecaster, s.target"""):  # M3: PIT draws tied to rows
        rps[(forecaster, target)][day] = score
        logs[(forecaster, target)][day] = log_score
        calib[(forecaster, target)].append((dist.normalize(json.loads(probs_json)), outcome))
    kinds = dict(conn.execute("SELECT kind, COUNT(*) FROM ledger GROUP BY kind").fetchall())
    rows = []
    for forecaster, target in sorted(rps):
        scores = rps[(forecaster, target)]
        log_scores = logs[(forecaster, target)]
        row = {"id": forecaster, "target": target, "n": len(scores),
               "mean_rps": sum(scores.values()) / len(scores),
               "mean_log_score": sum(log_scores.values()) / len(log_scores)}
        for ref in REFERENCES:
            row[f"skill_vs_{ref}"] = (None if ref == forecaster
                                      else _skill(scores, rps.get((ref, target), {})))
            row[f"log_skill_vs_{ref}"] = (None if ref == forecaster
                                          else _skill(log_scores, logs.get((ref, target), {})))
        rows.append(row)
    primary_cmp = _comparison(rps, PRIMARY_FORECASTER, "persistence", PRIMARY_TARGET)
    primary = {"target": PRIMARY_TARGET, "forecaster": PRIMARY_FORECASTER,
               "reference": "persistence", "n": primary_cmp["n"],
               "skill_vs_persistence": primary_cmp["skill_vs_reference"],
               "note": primary_cmp["note"]}
    secondary = [_comparison(rps, PRIMARY_FORECASTER, "persistence", t)
                 for t in TARGETS if t != PRIMARY_TARGET]
    seven = _comparison(rps, NOTES_FORECASTER, PRIMARY_FORECASTER, PRIMARY_TARGET)
    paired_days = set(rps.get((NOTES_FORECASTER, PRIMARY_TARGET), {})) & set(
        rps.get((PRIMARY_FORECASTER, PRIMARY_TARGET), {}))
    seven["days_with_notes"] = _days_with_notes(conn, paired_days)
    secondary.append(seven)
    calibration: dict[str, dict[str, list]] = defaultdict(dict)
    for (forecaster, target), pairs in sorted(calib.items()):
        calibration[forecaster][target] = dist.calibration_bins(pairs)
    return {
        "generated_at": db.utc_stamp(),
        "days_locked": conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
        "days_scored": kinds.get("outcome", 0),
        "days_voided": kinds.get("void", 0),
        "days_no_outcome": kinds.get("no_outcome", 0),
        "primary": primary,
        "secondary": secondary,
        "forecasters": rows,
        "calibration": dict(calibration),
    }


def _days_with_notes(conn: sqlite3.Connection, days: set[str]) -> int:
    """How many of forecaster 7's paired days it had at least one hypothesis to read."""
    try:
        rows = conn.execute("SELECT day, notes_json FROM lock_notes WHERE forecaster = ?",
                            (NOTES_FORECASTER,)).fetchall()
    except sqlite3.OperationalError:
        return 0
    return sum(1 for day, notes in rows if day in days and json.loads(notes))


def _fmt(x: float | None, digits: int = 3) -> str:
    return "–" if x is None else f"{x:.{digits}f}"


def _skill_cell(skill: dict | None) -> str:
    if skill is None:
        return "<td>–</td>"
    return f"<td>{_fmt(skill['skill'], 2)} <small>(n = {skill['n']})</small></td>"


CSS = """
:root { --bg: #f7f7f4; --fg: #1b1f1d; --muted: #5d6662; --line: #d8dcd6; --accent: #2f4aa0;
        color-scheme: light; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #131615; --fg: #e5e9e6; --muted: #9ca5a0; --line: #2d3330; --accent: #8ea4f0;
          color-scheme: dark; }
}
body { background: var(--bg); color: var(--fg); margin: 0; padding: 32px 16px 64px;
       font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 860px; margin: 0 auto; }
h1 { font-size: 28px; margin: 0 0 6px; } h2 { font-size: 19px; margin: 32px 0 8px; }
p { max-width: 68ch; } small, .muted { color: var(--muted); }
.wrap { overflow-x: auto; border: 1px solid var(--line); }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--line); }
th { font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
.big { font-size: 22px; font-weight: 600; color: var(--accent); }
"""


def _interval(c: dict) -> str:
    if not c["skill_vs_reference"]:
        return html.escape(c["note"])
    point, lo, hi = c["skill_vs_reference"]
    return f"{point:+.2f} ({lo:+.2f} to {hi:+.2f})"


def render_html(board: dict) -> str:
    p = board["primary"]
    if p["skill_vs_persistence"]:
        point, lo, hi = p["skill_vs_persistence"]
        headline = f"<span class='big'>{point:+.2f}</span> (95% interval {lo:+.2f} to {hi:+.2f}, n = {p['n']})"
    else:
        headline = f"<span class='big'>not yet</span> ({html.escape(p['note'])}; n = {p['n']})"
    body = "".join(
        f"<tr><td>{html.escape(r['id'])}</td><td>{r['target']}</td><td>n = {r['n']}</td>"
        f"<td>{_fmt(r['mean_rps'])}</td>{_skill_cell(r['skill_vs_climatology'])}"
        f"{_skill_cell(r['skill_vs_persistence'])}<td>{_fmt(r.get('mean_log_score'))}</td></tr>"
        for r in board["forecasters"])
    secondary = "".join(
        f"<tr><td>{html.escape(c['forecaster'])}</td><td>{html.escape(c['reference'])}</td>"
        f"<td>{c['target']}</td><td>n = {c['n']}</td><td>{_interval(c)}</td></tr>"
        for c in board.get("secondary", []))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Forecast Ledger Scoreboard</title><style>{CSS}</style></head>
<body><main>
<h1>Forecast ledger scoreboard</h1>
<p class="muted">Calibrated Health Agent · updated {html.escape(board['generated_at'][:16])} UTC ·
days locked {board['days_locked']} · scored {board['days_scored']} · void {board['days_voided']}
· no journal {board['days_no_outcome']}</p>
<p>Every morning seven forecasters bet on one person's evening mood, energy and soreness (1–10).
The bets are locked and hash-chained before the journal exists, then scored with the ranked
probability score (lower is better). Skill above 0 beats the reference; below 0 loses to it.
Results are published as-is, including forecasters that lose to persistence, and the real n
is shown next to every number. The chain hashes are in <a href="chain.csv">chain.csv</a>.</p>
<h2>Primary endpoint</h2>
<p>{html.escape(p['forecaster'])} vs persistence, {p['target']} skill: {headline}</p>
<h2>Secondary endpoints</h2>
<div class="wrap"><table>
<thead><tr><th>Forecaster</th><th>Reference</th><th>Target</th><th>Paired n</th>
<th>RPS skill (95% interval)</th></tr></thead>
<tbody>{secondary}</tbody></table></div>
<h2>All forecasters</h2>
<div class="wrap"><table>
<thead><tr><th>Forecaster</th><th>Target</th><th>Scored</th><th>Mean RPS</th>
<th>Skill vs climatology</th><th>Skill vs persistence</th><th>Mean log score</th></tr></thead>
<tbody>{body}</tbody></table></div>
<p class="muted">Pre-registered analysis plan: docs/ledger/analysis-plan.md in the project
repository; its hash is the first line of chain.csv. Wellness forecasting, not medical advice.</p>
</main></body></html>
"""
