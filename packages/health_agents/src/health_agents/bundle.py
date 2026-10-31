"""The data handed to sandboxed code, as of one day, and its fingerprint.

`build(conn, as_of)` returns `{"as_of", "frames": {...}}`, each frame a list of records the
sandbox turns into a DataFrame:

- `days`: one row per civil day up to `as_of` with the **lock-time** columns (what the
  morning lock could know: the ledger's feature snapshot, yesterday's ratings and tags)
  plus that day's outcome (`mood`, `energy`, `soreness`, null when not journalled);
- `journal`: outcomes with tags and the note, wrapped as untrusted text;
- `metrics`: daily values per metric with a `worn` flag;
- `misses` (investigator only): settled scores per forecaster and target.

Nothing dated after `as_of` appears in any frame, and the ledger's forecasts never do:
`misses` comes from `scores`, which exist only for settled days.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta

from health_ledger import features, wear
from health_ledger.forecasters.base import TARGETS

from .untrusted import wrap

LOCK_STATIC = ("day", "weekday", "sleep_minutes", "hrv_rmssd", "resting_hr", "readiness",
               "steps_prev_day", "mood_prev", "energy_prev", "soreness_prev")
_FAMILY = {"sleep": "sleep", "daily-heart-rate-variability": "overnight",
           "daily-resting-heart-rate": "overnight", "heart-rate-variability": "overnight"}


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def _tag_slugs(conn: sqlite3.Connection) -> list[str]:
    seen: set[str] = set()
    for (tags,) in conn.execute("SELECT tags FROM journal_submissions WHERE tags IS NOT NULL"):
        try:
            seen.update(slug(t) for t in json.loads(tags) if isinstance(t, str) and slug(t))
        except ValueError:
            continue
    return sorted(seen)


def lock_columns(conn: sqlite3.Connection) -> list[str]:
    return [*LOCK_STATIC, *(f"tag_prev_{s}" for s in _tag_slugs(conn))]


def _outcomes(conn: sqlite3.Connection, as_of: date) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT o.date, o.mood, o.energy, o.soreness, s.tags, s.note FROM journal_outcome o "
        "JOIN journal_submissions s ON s.id = o.submission_id WHERE o.date <= ? ORDER BY o.date",
        (as_of.isoformat(),))
    out = {}
    for day, mood, energy, soreness, tags, note in rows:
        try:
            labels = [t for t in json.loads(tags or "[]") if isinstance(t, str)]
        except ValueError:
            labels = []
        out[day] = {"mood": mood, "energy": energy, "soreness": soreness, "tags": labels,
                    "note": note}
    return out


def _first_day(conn: sqlite3.Connection) -> date | None:
    row = conn.execute("SELECT MIN(d) FROM (SELECT MIN(date) d FROM daily_metrics "
                       "UNION ALL SELECT MIN(date) FROM journal_outcome)").fetchone()
    return date.fromisoformat(row[0]) if row and row[0] else None


_DETAIL_UNTRUSTED = {
    "sleep_sessions": (("source", "data_source"),),
    "exercise_sessions": (("name", "workout_name"), ("source", "data_source")),
}
DETAIL_FRAMES = ("sleep_sessions", "exercise_sessions", "night_vitals", "activity_breakdown",
                 "weather_daily")


def build(conn: sqlite3.Connection, as_of: date, *, investigator: bool = False,
          days_back: int = 365) -> dict:
    tags = _tag_slugs(conn)
    outcomes = _outcomes(conn, as_of)
    first = _first_day(conn)
    start = max(as_of - timedelta(days=days_back), first) if first else as_of + timedelta(days=1)
    days = []
    d = start
    while d <= as_of:
        snap, _ = features.snapshot(conn, d)
        prev_day = outcomes.get((d - timedelta(days=1)).isoformat())
        prev = snap["journal_prev_day"] or {}
        row = {k: snap.get(k) for k in LOCK_STATIC[:7]}
        row.update({f"{t}_prev": prev.get(t) for t in TARGETS})
        prev_slugs = {slug(t) for t in prev_day["tags"]} if prev_day else set()
        row.update({f"tag_prev_{s}": (s in prev_slugs) if prev_day else None for s in tags})
        today = outcomes.get(d.isoformat())
        row.update({t: today[t] if today else None for t in TARGETS})
        days.append(row)
        d += timedelta(days=1)
    journal = [{"date": day, **{t: o[t] for t in TARGETS}, "tags": o["tags"],
                "note": wrap("journal_note", o["note"])} for day, o in outcomes.items()]
    worn_cache: dict[str, dict[str, bool]] = {}
    metrics = []
    for day, metric, value in conn.execute(
            "SELECT date, data_type, agg_value FROM daily_metrics WHERE date <= ? AND date >= ? "
            "ORDER BY date, data_type", (as_of.isoformat(), start.isoformat())):
        if day not in worn_cache:
            worn_cache[day] = wear.worn(conn, date.fromisoformat(day))
        metrics.append({"date": day, "metric": metric, "value": value,
                        "worn": worn_cache[day][_FAMILY.get(metric, "day")]})
    frames: dict[str, list] = {"days": days, "journal": journal, "metrics": metrics}
    existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in DETAIL_FRAMES:  # schema v5 detail and weather, when the database has them
        if table in existing:
            cur = conn.execute(f"SELECT * FROM {table} WHERE date <= ? AND date >= ? ORDER BY date",
                               (as_of.isoformat(), start.isoformat()))
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
            for row in rows:  # typed names and sources stay data, as in the SQL guard
                for col, label in _DETAIL_UNTRUSTED.get(table, ()):
                    if row.get(col):
                        row[col] = wrap(label, row[col])
            frames[table] = rows
    if investigator:
        frames["misses"] = [
            {"day": r[0], "forecaster": r[1], "target": r[2], "outcome": r[3], "rps": r[4]}
            for r in conn.execute("SELECT day, forecaster, target, outcome, rps FROM scores "
                                  "WHERE day <= ? ORDER BY day, forecaster, target",
                                  (as_of.isoformat(),))]
    return {"as_of": as_of.isoformat(), "frames": frames}


def lock_view(bundle: dict, cols: list[str]) -> dict:
    """Only the lock-time columns of `days`, and no other frame: what a hypothesis condition
    may see. Outcomes, notes, metrics and misses are not in it at all."""
    days = [{c: row.get(c) for c in cols} for row in bundle["frames"]["days"]]
    return {"as_of": bundle["as_of"], "frames": {"days": days}}


def data_hash(bundle: dict) -> str:
    return features.sha256(features.canonical(bundle))


def latest_settled_day(conn: sqlite3.Connection) -> date | None:
    row = conn.execute("SELECT MAX(day) FROM ledger WHERE kind IN "
                       "('outcome', 'void', 'no_outcome')").fetchone()
    return date.fromisoformat(row[0]) if row and row[0] else None
