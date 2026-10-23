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

3. **Fresh about its freshness.** The tools read a local copy of the database,
   so they say how old it is: `describe_substrate` reports the last successful
   sync per type and the recorded vs bucket generation, and the series tools
   carry an `as_of` block. "Today" is the owner's civil day (`Settings.timezone`).

Each returns a plain dict so ADK can serialise it and the model can read it
without a schema round-trip.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import timedelta

from health_core.settings import get_settings
from health_data import civil, db, store

MAX_ROWS = 500

# anomalies and correlations were written by the retired Phase 0 analysis loop and are
# no longer refreshed; Phase 2 replaces them.
HISTORICAL_NOTE = (
    "historical: computed by the retired Phase 0 analysis loop and no longer refreshed; "
    "say so if you use it"
)


def _ro_connect() -> sqlite3.Connection:
    """A connection that cannot write, enforced by SQLite itself."""
    conn = sqlite3.connect(f"file:{db.DB_PATH}?mode=ro", uri=True)
    try:
        db.check_schema(conn, db.DB_PATH)
    except BaseException:
        conn.close()
        raise
    conn.row_factory = sqlite3.Row
    return conn


def _since(days: int) -> str:
    return (civil.today() - timedelta(days=max(1, days))).isoformat()


def _last_sync(conn: sqlite3.Connection, metric: str) -> str | None:
    row = conn.execute(
        "SELECT last_synced_at FROM sync_state WHERE data_type = ?", (metric,)
    ).fetchone()
    return row["last_synced_at"] if row else None


def _as_of(conn: sqlite3.Connection, metric: str | None = None) -> dict:
    """When the local data was last refreshed, and what "today" means."""
    out: dict = {"today": civil.today().isoformat(), "timezone": get_settings().timezone}
    if metric is not None:
        out["last_synced_at"] = _last_sync(conn, metric)
    return out


def _generations() -> dict:
    """Recorded (local) vs bucket generation of the database, when knowable."""
    settings = get_settings()
    out: dict = {"recorded_generation": store.recorded_generation()}
    if not settings.db_bucket:
        out["bucket_generation"] = None
        out["note"] = "CHA_DB_BUCKET not set; cannot compare with the bucket"
        return out
    try:
        out["bucket_generation"] = store.remote_generation(settings.db_bucket, settings.db_object)
        out["last_check"] = store.read_heartbeat(settings.db_bucket, settings.db_object)
    except Exception as exc:  # network or auth: report, don't fail the tool
        out["bucket_generation"] = None
        out["note"] = f"bucket unreachable ({type(exc).__name__})"
        return out
    out["local_is_current"] = out["bucket_generation"] == out["recorded_generation"]
    return out


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
        mean_value, last_synced_at}. `total` is how many metrics have data;
        `as_of` says what "today" is.
    """
    with _ro_connect() as conn:
        rows = _rows(conn.execute("""
            SELECT d.data_type AS metric, COUNT(*) AS days,
                   MIN(d.date) AS first_date, MAX(d.date) AS last_date,
                   ROUND(AVG(d.agg_value), 2) AS mean_value,
                   s.last_synced_at AS last_synced_at
            FROM daily_metrics d LEFT JOIN sync_state s ON s.data_type = d.data_type
            GROUP BY d.data_type ORDER BY d.data_type
        """))
        as_of = _as_of(conn)
    return {"metrics": rows, "total": len(rows), "as_of": as_of}


def describe_substrate() -> dict:
    """Summarise what data exists: table sizes, sync cursors, coverage.

    Use this to answer "what do you know about me?" without guessing.

    Returns:
        dict: row counts per table; `freshness` with the last successful sync
        per metric (UTC), the newest of those, the last journal import, the
        recorded vs bucket generation of the database (a mismatch means this
        local copy is stale — say so before answering about recent days), and
        `last_check`: the sync job's latest heartbeat (`checked_at`, `ok`,
        `last_ok_at`). A run that found no new data does not push, so
        `last_check` can be newer than every `last_synced_at`.
    """
    with _ro_connect() as conn:
        counts = {}
        for t in ("raw_points", "daily_metrics", "journal_submissions", "journal_outcome",
                  "anomalies", "correlations"):
            try:
                counts[t] = conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            except sqlite3.OperationalError:
                counts[t] = None
        cursors = _rows(conn.execute(
            "SELECT data_type AS metric, last_synced_at FROM sync_state "
            "WHERE data_type NOT LIKE 'backfill:%' ORDER BY data_type"
        ))
        journal = conn.execute("SELECT MAX(imported_at) m FROM journal_submissions").fetchone()["m"]
        as_of = _as_of(conn)
    freshness = {
        **as_of,
        "last_sync_by_metric": {c["metric"]: c["last_synced_at"] for c in cursors},
        "newest_sync": max((c["last_synced_at"] for c in cursors), default=None),
        "last_journal_import": journal,
        **_generations(),
    }
    return {"row_counts": counts, "sync_state": cursors, "freshness": freshness}


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
    with _ro_connect() as conn:
        rows = _rows(conn.execute("""
            SELECT date, ROUND(agg_value, 3) AS value FROM daily_metrics
            WHERE data_type = ? AND date >= ? ORDER BY date
        """, (metric, _since(days))))
        as_of = _as_of(conn, metric)
    values = [r["value"] for r in rows]
    stats = {
        "min": min(values), "max": max(values),
        "mean": round(sum(values) / len(values), 3),
    } if values else {}
    return {"metric": metric, "series": rows, "n": len(rows), "stats": stats, "as_of": as_of}


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
    today = civil.today()  # excluded: a part-finished day is not comparable
    r_start = (today - timedelta(days=window_days)).isoformat()
    p_start = (today - timedelta(days=window_days * 2)).isoformat()
    with _ro_connect() as conn:
        q = """SELECT AVG(agg_value) m, COUNT(*) n FROM daily_metrics
               WHERE data_type=? AND date >= ? AND date < ?"""
        recent = conn.execute(q, (metric, r_start, today.isoformat())).fetchone()
        prior = conn.execute(q, (metric, p_start, r_start)).fetchone()
        as_of = _as_of(conn, metric)
    rm, pm = recent["m"], prior["m"]
    pct = round((rm - pm) / pm * 100, 1) if (rm is not None and pm) else None
    return {
        "metric": metric, "window_days": window_days,
        "recent_mean": round(rm, 3) if rm is not None else None,
        "prior_mean": round(pm, 3) if pm is not None else None,
        "change_pct": pct,
        "n_recent": recent["n"], "n_prior": prior["n"],
        "as_of": as_of,
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
        severity}] newest first, where severity is "watch" or "alert", and
        `note`: these rows are historical and no longer refreshed.
    """
    since = _since(days)
    with _ro_connect() as conn:
        rows = _rows(conn.execute("""
            SELECT date, data_type AS metric, ROUND(value,3) AS value,
                   ROUND(baseline_mean,3) AS baseline_mean,
                   ROUND(z_score,2) AS z_score, severity
            FROM anomalies WHERE date >= ? ORDER BY date DESC
        """, (since,)))
    return {"anomalies": rows, "n": len(rows), "note": HISTORICAL_NOTE}


def get_correlations(min_abs_r: float = 0.3) -> dict:
    """Correlations between metric pairs, same-day and next-day lag.

    Correlation is not causation, and on a single person's data it is weak
    evidence at best. Some pairs are definitional — distance and steps
    measure the same walking — so `definitional` flags the obvious ones.

    Args:
        min_abs_r: Minimum absolute Pearson r to return. Defaults to 0.3.

    Returns:
        dict: `correlations` is [{metric_a, metric_b, lag_days, r, n,
        definitional}] sorted by strength, and `note`: these rows are
        historical and no longer refreshed.
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
    return {"correlations": rows, "n": len(rows), "note": HISTORICAL_NOTE}


def get_journal(days: int = 30) -> dict:
    """Subjective daily entries: mood, energy, soreness, each 1-10.

    This is the only data no wearable can observe. When it is empty, say so
    — do not substitute an inference from activity data for how someone
    actually reported feeling.

    Args:
        days: How far back to read. Defaults to 30.

    Each date's entry is its outcome: the earliest valid submission inside
    its window (later edits and resubmissions are kept but not shown here).

    Returns:
        dict: `entries` is [{date, mood, energy, soreness, note}] newest first;
        `as_of` carries the owner's today and the last journal import time.
    """
    with _ro_connect() as conn:
        rows = _rows(conn.execute(
            "SELECT o.date, o.mood, o.energy, o.soreness, s.note "
            "FROM journal_outcome o JOIN journal_submissions s ON s.id = o.submission_id "
            "WHERE o.date >= ? ORDER BY o.date DESC", (_since(days),)
        ))
        as_of = _as_of(conn)
        as_of["last_journal_import"] = conn.execute(
            "SELECT MAX(imported_at) m FROM journal_submissions").fetchone()["m"]
    return {"entries": rows, "n": len(rows), "as_of": as_of}


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

    Schema: daily_metrics(date, data_type, agg_value, n_points) — `date` is
    the owner's civil day; raw_points(data_type, start_time, end_time, value,
    unit, source, civil_date); journal_outcome(date, mood, energy, soreness,
    submission_id); journal_submissions(date, mood, energy, soreness, note,
    submitted_at, status, reason); anomalies(date, data_type, value,
    baseline_mean, z_score, severity) and correlations(metric_a, metric_b,
    lag_days, r, n) — both historical, no longer refreshed;
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
