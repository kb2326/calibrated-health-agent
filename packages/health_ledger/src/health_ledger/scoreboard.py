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
from health_ledger.forecasters import gemini

TARGETS = ("mood", "energy", "soreness")
REFERENCES = ("climatology", "persistence")
PRIMARY_TARGET = "energy"
PRIMARY_MIN_N = 10


def _paired(a: dict[str, float], b: dict[str, float]) -> tuple[list[float], list[float]]:
    days = sorted(set(a) & set(b))
    return [a[d] for d in days], [b[d] for d in days]


def _skill(rps: dict[str, float], ref: dict[str, float]) -> dict | None:
    mine, theirs = _paired(rps, ref)
    if not mine:
        return None
    return {"skill": dist.skill(sum(mine) / len(mine), sum(theirs) / len(theirs)), "n": len(mine)}


def build(conn: sqlite3.Connection) -> dict:
    rps: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    calib: dict[tuple[str, str], list] = defaultdict(list)
    for day, forecaster, target, outcome, score, probs_json in conn.execute(
            """SELECT s.day, s.forecaster, s.target, s.outcome, s.rps, f.probs_json
               FROM scores s JOIN forecasts f USING (day, forecaster, target)"""):
        rps[(forecaster, target)][day] = score
        calib[(forecaster, target)].append((dist.normalize(json.loads(probs_json)), outcome))
    kinds = dict(conn.execute("SELECT kind, COUNT(*) FROM ledger GROUP BY kind").fetchall())
    rows = []
    for forecaster, target in sorted(rps):
        scores = rps[(forecaster, target)]
        row = {"id": forecaster, "target": target, "n": len(scores),
               "mean_rps": sum(scores.values()) / len(scores)}
        for ref in REFERENCES:
            row[f"skill_vs_{ref}"] = (None if ref == forecaster
                                      else _skill(scores, rps.get((ref, target), {})))
        rows.append(row)
    mine, ref = _paired(rps.get((gemini.FORECASTER_ID, PRIMARY_TARGET), {}),
                        rps.get(("persistence", PRIMARY_TARGET), {}))
    primary = {"target": PRIMARY_TARGET, "forecaster": gemini.FORECASTER_ID,
               "reference": "persistence", "n": len(mine), "skill_vs_persistence": None,
               "note": f"n below {PRIMARY_MIN_N}"}
    if len(mine) >= PRIMARY_MIN_N:
        primary["skill_vs_persistence"] = list(dist.block_bootstrap_skill(mine, ref))
        primary["note"] = "95% interval: paired moving-block bootstrap, block 7, 2000 resamples"
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
        "forecasters": rows,
        "calibration": dict(calibration),
    }


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
        f"{_skill_cell(r['skill_vs_persistence'])}</tr>" for r in board["forecasters"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Forecast Ledger Scoreboard</title><style>{CSS}</style></head>
<body><main>
<h1>Forecast ledger scoreboard</h1>
<p class="muted">Calibrated Health Agent · updated {html.escape(board['generated_at'][:16])} UTC ·
days locked {board['days_locked']} · scored {board['days_scored']} · void {board['days_voided']}
· no journal {board['days_no_outcome']}</p>
<p>Every morning six forecasters bet on one person's evening mood, energy and soreness (1–10).
The bets are locked and hash-chained before the journal exists, then scored with the ranked
probability score (lower is better). Skill above 0 beats the reference; below 0 loses to it.
Results are published as-is, including forecasters that lose to persistence, and the real n
is shown next to every number. The chain hashes are in <a href="chain.csv">chain.csv</a>.</p>
<h2>Primary endpoint</h2>
<p>{html.escape(p['forecaster'])} vs persistence, {p['target']} skill: {headline}</p>
<h2>All forecasters</h2>
<div class="wrap"><table>
<thead><tr><th>Forecaster</th><th>Target</th><th>Scored</th><th>Mean RPS</th>
<th>Skill vs climatology</th><th>Skill vs persistence</th></tr></thead>
<tbody>{body}</tbody></table></div>
<p class="muted">Pre-registered analysis plan: docs/ledger/analysis-plan.md in the project
repository; its hash is the first line of chain.csv. Wellness forecasting, not medical advice.</p>
</main></body></html>
"""
