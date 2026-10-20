"""Digest loop — Phase 2/3, weekly.

Reads the outputs the other stages already wrote to stage_output/anomalies/
correlations (the orchestration-graph handoff) and produces:
  - data/digest_<week>.md   a human-readable weekly report
  - data/dashboard_data.json  time series + correlation graph for the Artifact
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd
import yaml
from health_core.settings import get_settings

from health_data import db

CONFIG = yaml.safe_load((get_settings().config_dir / "health.yaml").read_text())
DATA_DIR = get_settings().data_dir


def _week_deltas(conn, end_day: date) -> list[dict]:
    this_start = (end_day - timedelta(days=6)).isoformat()
    prev_start = (end_day - timedelta(days=13)).isoformat()
    prev_end = (end_day - timedelta(days=7)).isoformat()

    rows = []
    for data_type in CONFIG["data_types"]:
        this_week = pd.read_sql_query(
            "SELECT agg_value FROM daily_metrics WHERE data_type=? AND date>=? AND date<=?",
            conn, params=(data_type, this_start, end_day.isoformat()),
        )["agg_value"]
        prev_week = pd.read_sql_query(
            "SELECT agg_value FROM daily_metrics WHERE data_type=? AND date>=? AND date<?",
            conn, params=(data_type, prev_start, prev_end),
        )["agg_value"]
        if this_week.empty:
            continue
        this_avg = this_week.mean()
        prev_avg = prev_week.mean() if not prev_week.empty else None
        pct = ((this_avg - prev_avg) / prev_avg * 100) if prev_avg else None
        rows.append({
            "data_type": data_type, "this_week_avg": round(float(this_avg), 2),
            "prev_week_avg": round(float(prev_avg), 2) if prev_avg else None,
            "pct_change": round(float(pct), 1) if pct is not None else None,
        })
    return rows


def run(end_date: str | None = None) -> dict:
    db.init_db()
    end_day = date.fromisoformat(end_date) if end_date else date.today()
    week_key = end_day.isocalendar()
    week_label = f"{week_key.year}-W{week_key.week:02d}"

    # Orchestration-graph handoff: consume what the upstream stages reported
    # instead of re-deriving it, so the digest states the provenance of its
    # own numbers — including which stages failed or never ran this cycle.
    upstream = {
        "ingest": db.read_stage_output("ingest", end_day.isoformat()),
        "analyze": db.read_stage_output("analyze", (end_day - timedelta(days=1)).isoformat()),
        "correlate": db.read_stage_output("correlate", end_day.isoformat()),
        "learn": db.read_stage_output("learn", end_day.isoformat()),
    }
    provenance = {
        "stages_run": sorted(k for k, v in upstream.items() if v),
        "stages_missing": sorted(k for k, v in upstream.items() if not v),
    }
    if upstream["learn"]:
        provenance["signals_scored"] = upstream["learn"].get("scored", 0)
    if upstream["analyze"]:
        provenance["metrics_skipped_stale"] = upstream["analyze"].get("_skipped_failed_ingest", [])

    with db.connect() as conn:
        deltas = _week_deltas(conn, end_day)
        anomalies = pd.read_sql_query(
            "SELECT * FROM anomalies WHERE date >= ? ORDER BY date",
            conn, params=((end_day - timedelta(days=6)).isoformat(),),
        ).to_dict("records")
        correlations = pd.read_sql_query(
            "SELECT * FROM correlations ORDER BY ABS(r) DESC LIMIT 15", conn
        ).to_dict("records")
        series = pd.read_sql_query(
            "SELECT date, data_type, agg_value FROM daily_metrics WHERE date >= ?",
            conn, params=((end_day - timedelta(days=28)).isoformat(),),
        ).to_dict("records")
        journal = pd.read_sql_query(
            "SELECT * FROM journal WHERE date >= ?",
            conn, params=((end_day - timedelta(days=28)).isoformat(),),
        ).to_dict("records")

    # --- markdown report ---
    lines = [f"# Health Digest — week ending {end_day.isoformat()} ({week_label})\n"]
    lines.append("## Trends vs. previous week\n")
    for d in deltas:
        arrow = "" if d["pct_change"] is None else ("up" if d["pct_change"] > 0 else "down")
        pct = "n/a" if d["pct_change"] is None else f"{d['pct_change']:+.1f}%"
        lines.append(f"- **{d['data_type']}**: {d['this_week_avg']} avg/day ({arrow} {pct})")
    lines.append("\n## Anomalies flagged this week\n")
    if anomalies:
        for a in anomalies:
            lines.append(f"- {a['date']} · {a['data_type']} · {a['severity']} (z={a['z_score']:+.2f})")
    else:
        lines.append("- none")
    lines.append("\n## Strongest correlations (all-time)\n")
    for c in correlations:
        lag = f", lag {c['lag_days']}d" if c["lag_days"] else ""
        lines.append(f"- {c['metric_a']} <-> {c['metric_b']}: r={c['r']:+.2f} (n={c['n']}{lag})")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    md_path = DATA_DIR / f"digest_{week_label}.md"
    md_path.write_text("\n".join(lines))

    dashboard = {
        "week_label": week_label, "generated_at": db.now_iso(),
        "provenance": provenance,
        "deltas": deltas, "anomalies": anomalies, "correlations": correlations,
        "series": series, "journal": journal,
    }
    (DATA_DIR / "dashboard_data.json").write_text(json.dumps(dashboard, indent=2))

    db.write_stage_output("digest", week_label, {"md_path": str(md_path), "deltas": deltas, "provenance": provenance})
    return dashboard


if __name__ == "__main__":
    out = run()
    print(f"Wrote data/digest_{out['week_label']}.md and data/dashboard_data.json")
