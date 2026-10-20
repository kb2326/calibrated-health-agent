"""Correlation graph — Phase 3.

Builds a graph over your own metrics: nodes are tracked data types + journal
fields, edges are same-day and next-day-lag Pearson correlations above a
minimum strength/sample-size threshold. This is the "data graph" half of
the graph-engineering story (the "orchestration graph" half is the
ingest -> analyze -> correlate -> digest handoff via stage_output).
"""
from __future__ import annotations

from datetime import date
from itertools import combinations

import pandas as pd
import yaml
from health_core.settings import get_settings

from health_data import db

CONFIG = yaml.safe_load((get_settings().config_dir / "health.yaml").read_text())
C = CONFIG["correlation"]


def _load_wide_frame(conn) -> pd.DataFrame:
    metrics = pd.read_sql_query(
        "SELECT date, data_type, agg_value FROM daily_metrics", conn
    )
    wide = metrics.pivot_table(index="date", columns="data_type", values="agg_value")

    journal = pd.read_sql_query(
        f"SELECT date, {', '.join(CONFIG['journal_fields'])} FROM journal", conn
    ).set_index("date")

    return wide.join(journal, how="outer").sort_index()


def _score_pair(conn, frame, lead: str, follow: str, lag: int) -> dict | None:
    """Correlate `lead` against `follow` shifted `lag` days later.

    Returns an edge dict when the pair clears both the effect-size and
    sample-count floors, otherwise None — a weak correlation on a personal
    dataset is noise, and reporting it would be the failure mode the
    literature warns about for n-of-1 wearable analysis.
    """
    a = frame[lead]
    b = frame[follow].shift(-lag) if lag else frame[follow]
    paired = pd.concat([a, b], axis=1).dropna()
    n = len(paired)
    if n < C["min_n"]:
        return None
    r = paired.iloc[:, 0].corr(paired.iloc[:, 1])
    if r is None or pd.isna(r) or abs(r) < C["min_abs_r"]:
        return None
    r = round(float(r), 4)
    conn.execute(
        """INSERT INTO correlations (metric_a, metric_b, lag_days, r, n, computed_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(metric_a, metric_b, lag_days) DO UPDATE SET
             r=excluded.r, n=excluded.n, computed_at=excluded.computed_at""",
        (lead, follow, lag, r, n, db.now_iso()),
    )
    return {"a": lead, "b": follow, "lag_days": lag, "r": r, "n": n}


def run() -> dict:
    db.init_db()
    # Edges that fell below threshold since the last run would otherwise
    # linger forever; the table is cheap to rebuild from daily_metrics.
    with db.connect() as conn:
        conn.execute("DELETE FROM correlations")
    with db.connect() as conn:
        frame = _load_wide_frame(conn)
        # Reindex onto a continuous daily range before shifting. The index is
        # a sorted list of date strings with gaps in it — sleep covers 22 rows
        # across 31 days — so a positional shift(-1) can jump several calendar
        # days and "lag 1" would not mean "one day later".
        frame.index = pd.to_datetime(frame.index)
        frame = frame.reindex(
            pd.date_range(frame.index.min(), frame.index.max(), freq="D")
        )
        columns = list(frame.columns)
        edges = []

        for col_a, col_b in combinations(columns, 2):
            for lag in C["lags_days"]:
                # At a non-zero lag "a leads b" and "b leads a" are different
                # claims. Testing only one direction let pivot column order
                # decide which hypothesis got examined.
                pairs = [(col_a, col_b)] if lag == 0 else [(col_a, col_b), (col_b, col_a)]
                for lead, follow in pairs:
                    edge = _score_pair(conn, frame, lead, follow, lag)
                    if edge:
                        edges.append(edge)

    result = {"nodes": columns, "edges": edges}
    db.write_stage_output("correlate", date.today().isoformat(), result)
    return result


if __name__ == "__main__":
    out = run()
    print(f"{len(out['nodes'])} nodes, {len(out['edges'])} edges above |r|>={C['min_abs_r']}\n")
    for e in sorted(out["edges"], key=lambda e: -abs(e["r"])):
        lag = f" (lag {e['lag_days']}d)" if e["lag_days"] else ""
        print(f"  {e['a']:28s} <-> {e['b']:28s}  r={e['r']:+.2f}{lag}  n={e['n']}")
