"""The morning lock: every forecaster bets on today, and the bets are sealed in the chain.

A lock is due for today (owner-zone civil day) when it has not happened yet and either
last night's sleep has arrived (a `sleep` daily value dated today) or it is 12:00 or
later. Only today is ever locked: a missed day stays missed. The deadline lock records
which inputs were missing.

Forecasters run first (Gemini and TimesFM call the network), then the snapshot, every
(forecaster, target) row and the `lock` chain entry are written in one transaction. A
forecaster that raises abstains all targets with `error: <ExceptionType>`; a target it
leaves out abstains with `no forecast returned`.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime, time

from health_data import civil, db

from health_ledger import chain, features
from health_ledger.forecasters import FORECASTERS, TARGETS, Forecast, Forecaster

DEADLINE = time(12, 0)


def _today(now: datetime):
    return now.astimezone(civil.zone()).date()


def due(conn: sqlite3.Connection, now: datetime) -> bool:
    day = _today(now).isoformat()
    if conn.execute("SELECT 1 FROM snapshots WHERE day = ?", (day,)).fetchone():
        return False
    sleep = conn.execute("SELECT 1 FROM daily_metrics WHERE data_type = 'sleep' AND date = ?",
                         (day,)).fetchone()
    return sleep is not None or now.astimezone(civil.zone()).time() >= DEADLINE


def _rows(name: str, forecast: Forecast, day: str, locked_at: str) -> list[tuple]:
    rows = []
    for target in TARGETS:
        if target in forecast.probs:
            probs = json.dumps([round(p, 6) for p in forecast.probs[target]])
            rows.append((day, name, target, probs, None, locked_at))
        else:
            rows.append((day, name, target, None,
                         forecast.abstain.get(target, "no forecast returned"), locked_at))
    return rows


def lock_today(conn: sqlite3.Connection, now: datetime,
               forecasters: Mapping[str, Forecaster] = FORECASTERS) -> dict | None:
    if not due(conn, now):
        return None
    day = _today(now)
    snap, missing = features.snapshot(conn, day)
    locked_at = db.utc_stamp(now)
    rows: list[tuple] = []
    for name, forecaster in forecasters.items():
        try:
            forecast = forecaster(conn, day, snap)
        except Exception as exc:  # a broken forecaster abstains; the others still lock
            forecast = Forecast.abstain_all(f"error: {type(exc).__name__}")
        rows.extend(_rows(name, forecast, day.isoformat(), locked_at))
    snap_json = features.canonical(snap)
    snap_hash = features.sha256(snap_json)
    if conn.in_transaction:
        conn.commit()
    try:
        conn.execute("INSERT INTO snapshots VALUES (?, ?, ?, ?, ?)",
                     (day.isoformat(), snap_json, snap_hash, locked_at, json.dumps(missing)))
        conn.executemany(
            """INSERT INTO forecasts (day, forecaster, target, probs_json, abstain_reason,
                                      locked_at) VALUES (?, ?, ?, ?, ?, ?)""", rows)
        chain.append(conn, day.isoformat(), "lock", {
            "snapshot_hash": snap_hash,
            "forecasts_hash": features.sha256(features.canonical([list(r) for r in rows])),
        })
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {"day": day.isoformat(), "forecasters": len(forecasters),
            "abstained": sum(1 for r in rows if r[3] is None), "missing_inputs": len(missing)}
