"""Typed, read-only tools over the health substrate.

These are the agent's entire capability surface. Two properties are enforced
here rather than requested in a prompt:

1. **Read-only.** No tool writes to the Health API or mutates health data.
   `run_sql` accepts a single SELECT and rejects everything else, checked
   after stripping comments so a `--` prefix cannot smuggle a second
   statement past the guard.
2. **Grounded.** Every tool returns real rows from `data/health.db` with
   explicit sample counts. The published criticism of Google's own Gemini
   health coach is that it "doesn't actually anchor itself" on data it
   already has and asks about metrics already logged. Tools that always
   report `n` make that failure visible instead of plausible.

Each returns a plain dict so ADK can serialise it and the model can read it
without a schema round-trip.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta

from health_data import db

MAX_ROWS = 500


def _ro_connect() -> sqlite3.Connection:
    """A connection that cannot write, enforced by SQLite itself."""
    conn = sqlite3.connect(f"file:{db.DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchmany(MAX_ROWS)]


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def list_metrics() -> dict:
    """List every health metric available, with its coverage and date range.

    Call this first when you do not know which metrics exist. Never guess a
    metric name — the identifiers here are the only valid ones.

    Returns:
        dict: `metrics` is a list of {metric, days, first_date, last_date,
        latest_value}. `total` is how many metrics have data.
    """
    with _ro_connect() as conn:
        rows = _rows(conn.execute("""
            SELECT data_type AS metric, COUNT(*) AS days,
                   MIN(date) AS first_date, MAX(date) AS last_date,
                   ROUND(AVG(agg_value), 2) AS mean_value
            FROM daily_metrics GROUP BY data_type ORDER BY data_type
        """))
    return {"metrics": rows, "total": len(rows)}


def describe_substrate() -> dict:
    """Summarise what data exists: table sizes, sync cursors, coverage.

    Use this to answer "what do you know about me?" without guessing.

    Returns:
        dict: row counts per table, and the last sync time per metric.
    """
    with _ro_connect() as conn:
        counts = {}
        for t in ("raw_points", "daily_metrics", "anomalies",
                  "correlations", "journal", "predictions"):
            try:
                counts[t] = conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            except sqlite3.OperationalError:
                counts[t] = None
        cursors = _rows(conn.execute(
            "SELECT data_type AS metric, last_synced_at FROM sync_state ORDER BY data_type"
        ))
    return {"row_counts": counts, "sync_state": cursors}


# --------------------------------------------------------------------------
# Time series
# --------------------------------------------------------------------------


def get_metric_series(metric: str, days: int = 30) -> dict:
    """Daily values for one metric over the last N days.

    Args:
        metric: Exact identifier from `list_metrics`, e.g. "heart-rate".
        days: How many days back to read. Defaults to 30.

    Returns:
        dict: `series` is [{date, value}] oldest first; `n` is the count;
        `stats` carries min/max/mean. `n` is 0 when nothing is stored — say
        so rather than inventing a trend.
    """
    since = (date.today() - timedelta(days=max(1, days))).isoformat()
    with _ro_connect() as conn:
        rows = _rows(conn.execute("""
            SELECT date, ROUND(agg_value, 3) AS value FROM daily_metrics
            WHERE data_type = ? AND date >= ? ORDER BY date
        """, (metric, since)))
    values = [r["value"] for r in rows]
    stats = {
        "min": min(values), "max": max(values),
        "mean": round(sum(values) / len(values), 3),
    } if values else {}
    return {"metric": metric, "series": rows, "n": len(rows), "stats": stats}


def compare_periods(metric: str, window_days: int = 7) -> dict:
    """Compare the most recent window against the window before it.

    Args:
        metric: Exact identifier from `list_metrics`.
        window_days: Length of each window in days. Defaults to 7.

    Returns:
        dict: means for both windows, absolute and percent change, and the
        sample count in each. A change computed from very few days is weak
        evidence — report `n_recent` and `n_prior` alongside any claim.
    """
    today = date.today()
    r_start = (today - timedelta(days=window_days)).isoformat()
    p_start = (today - timedelta(days=window_days * 2)).isoformat()
    with _ro_connect() as conn:
        q = """SELECT AVG(agg_value) m, COUNT(*) n FROM daily_metrics
               WHERE data_type=? AND date >= ? AND date < ?"""
        recent = conn.execute(q, (metric, r_start, today.isoformat())).fetchone()
        prior = conn.execute(q, (metric, p_start, r_start)).fetchone()
    rm, pm = recent["m"], prior["m"]
    pct = round((rm - pm) / pm * 100, 1) if (rm is not None and pm) else None
    return {
        "metric": metric, "window_days": window_days,
        "recent_mean": round(rm, 3) if rm is not None else None,
        "prior_mean": round(pm, 3) if pm is not None else None,
        "change_pct": pct,
        "n_recent": recent["n"], "n_prior": prior["n"],
    }


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


def get_anomalies(days: int = 30) -> dict:
    """Days that scored beyond the baseline threshold for their metric.

    A high z-score is not automatically bad: an unusually long sleep and an
    unusually short one both deviate. Report the sign and let the user judge.

    Args:
        days: How far back to look. Defaults to 30.

    Returns:
        dict: `anomalies` is [{date, metric, value, baseline_mean, z_score,
        severity}] newest first, where severity is "watch" or "alert".
    """
    since = (date.today() - timedelta(days=max(1, days))).isoformat()
    with _ro_connect() as conn:
        rows = _rows(conn.execute("""
            SELECT date, data_type AS metric, ROUND(value,3) AS value,
                   ROUND(baseline_mean,3) AS baseline_mean,
                   ROUND(z_score,2) AS z_score, severity
            FROM anomalies WHERE date >= ? ORDER BY date DESC
        """, (since,)))
    return {"anomalies": rows, "n": len(rows)}


def get_correlations(min_abs_r: float = 0.3) -> dict:
    """Correlations between metric pairs, same-day and next-day lag.

    Correlation is not causation, and on a single person's data it is weak
    evidence at best. Some pairs are definitional — distance and steps
    measure the same walking — so `definitional` flags the obvious ones.

    Args:
        min_abs_r: Minimum absolute Pearson r to return. Defaults to 0.3.

    Returns:
        dict: `correlations` is [{metric_a, metric_b, lag_days, r, n,
        definitional}] sorted by strength.
    """
    obvious = {("distance", "steps"), ("steps", "distance"),
               ("active-minutes", "total-calories"), ("total-calories", "active-minutes")}
    with _ro_connect() as conn:
        rows = _rows(conn.execute("""
            SELECT metric_a, metric_b, lag_days, ROUND(r,4) AS r, n
            FROM correlations WHERE ABS(r) >= ? ORDER BY ABS(r) DESC
        """, (abs(min_abs_r),)))
    for row in rows:
        row["definitional"] = (row["metric_a"], row["metric_b"]) in obvious
    return {"correlations": rows, "n": len(rows)}


def get_journal(days: int = 30) -> dict:
    """Subjective daily entries: mood, energy, soreness, each 1-10.

    This is the only data no wearable can observe. When it is empty, say so
    — do not substitute an inference from activity data for how someone
    actually reported feeling.

    Args:
        days: How far back to read. Defaults to 30.

    Returns:
        dict: `entries` is [{date, mood, energy, soreness, note}] newest first.
    """
    since = (date.today() - timedelta(days=max(1, days))).isoformat()
    with _ro_connect() as conn:
        rows = _rows(conn.execute(
            "SELECT date, mood, energy, soreness, note FROM journal "
            "WHERE date >= ? ORDER BY date DESC", (since,)
        ))
    return {"entries": rows, "n": len(rows)}


def get_signal_reliability() -> dict:
    """How often each signal's predictions have actually come true.

    The learning loop scores past predictions against later journal entries.
    A signal with a low hit rate has not worked for this person and should
    be reported with that caveat, or not reported at all.

    Returns:
        dict: `signals` is [{signal, target, lag_days, hit_rate, n_scored,
        weight}]. An empty list means nothing has matured yet.
    """
    with _ro_connect() as conn:
        try:
            rows = _rows(conn.execute("""
                SELECT signal, target, lag_days, ROUND(hit_rate,3) AS hit_rate,
                       n_scored, ROUND(weight,3) AS weight
                FROM signal_weights WHERE n_scored > 0
                ORDER BY hit_rate DESC
            """))
        except sqlite3.OperationalError:
            return {"signals": [], "n": 0, "note": "learning loop has not run yet"}
    return {"signals": rows, "n": len(rows)}


# --------------------------------------------------------------------------
# Escape hatch: arbitrary read-only SQL
# --------------------------------------------------------------------------

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|"
    r"pragma|vacuum|reindex|begin|commit|rollback)\b", re.I,
)


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def run_sql(query: str) -> dict:
    """Run one read-only SELECT against the health database.

    Use this when the purpose-built tools cannot express the question —
    grouping, joins across tables, or a window the other tools do not cover.
    Numerical questions about wearable data need real computation, not
    estimation from a partial read; this is how you compute exactly.

    Schema: daily_metrics(date, data_type, agg_value, n_points),
    raw_points(data_type, start_time, end_time, value, unit, source),
    journal(date, mood, energy, soreness, note),
    anomalies(date, data_type, value, baseline_mean, z_score, severity),
    correlations(metric_a, metric_b, lag_days, r, n),
    sync_state(data_type, cursor_time, last_synced_at).

    Args:
        query: A single SELECT statement. Anything else is refused.

    Returns:
        dict: `rows` (capped at 500) and `n`, or `error` explaining the
        refusal. The connection is opened read-only, so a write cannot
        succeed even if the guard were bypassed.
    """
    cleaned = _strip_sql_comments(query).strip().rstrip(";").strip()
    if not cleaned:
        return {"error": "empty query", "rows": [], "n": 0}
    if ";" in cleaned:
        return {"error": "only a single statement is allowed", "rows": [], "n": 0}
    if not re.match(r"^\s*(select|with)\b", cleaned, re.I):
        return {"error": "only SELECT (or WITH ... SELECT) is allowed", "rows": [], "n": 0}
    if _FORBIDDEN.search(cleaned):
        return {"error": "query contains a non-read keyword", "rows": [], "n": 0}
    try:
        with _ro_connect() as conn:
            rows = _rows(conn.execute(cleaned))
    except sqlite3.Error as e:
        return {"error": f"sqlite: {e}", "rows": [], "n": 0}
    return {"rows": rows, "n": len(rows), "truncated": len(rows) == MAX_ROWS}
