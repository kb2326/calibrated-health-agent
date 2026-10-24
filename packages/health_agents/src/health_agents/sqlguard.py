"""Read-only SQL enforced by SQLite itself, not by keyword matching.

Three layers on every `run_sql` connection:

1. `mode=ro`: the file is opened read-only, so no write can succeed.
2. An authorizer: SQLite asks before every table read and function call. Only SELECTs,
   reads of allowlisted tables and allowlisted functions pass. The forecast ledger and
   agent tables are refused here (blinding), however the query spells or nests them.
   PRAGMA, ATTACH and `load_extension` are refused the same way.
3. A progress handler that interrupts any statement running past `TIME_LIMIT_S`.

Untrusted text columns (journal notes, device and source names, raw API payloads) read as
NULL through SQL whatever the query calls them (`SQLITE_IGNORE`): notes reach a prompt only
wrapped, through `get_journal`.

Python's `execute` already refuses more than one statement. The old keyword blocklist
(which refused harmless `replace()`) is gone.
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

TIME_LIMIT_S = 2.0

ALLOWED_TABLES = frozenset({
    "daily_metrics", "raw_points", "journal_submissions", "anomalies", "correlations",
    "sync_state", "devices", "sqlite_master", "sqlite_schema", "sqlite_temp_master",
})
BLINDED = frozenset({
    "forecasts", "snapshots", "scores", "ledger", "lock_notes", "receipts", "hypotheses",
    "hypothesis_status", "agent_runs",
})
UNTRUSTED_COLUMNS = frozenset({("journal_submissions", "note"), ("raw_points", "source"),
                               ("raw_points", "raw_json")})
UNTRUSTED_TABLES = frozenset({"devices"})  # every column: names and models typed by people
ALLOWED_FUNCTIONS = frozenset({
    # core scalar
    "abs", "coalesce", "ifnull", "iif", "instr", "length", "lower", "upper", "ltrim", "rtrim",
    "trim", "max", "min", "nullif", "printf", "format", "replace", "round", "substr",
    "substring", "typeof", "like", "glob", "char", "hex", "unicode", "sign", "concat",
    "concat_ws", "json_extract", "json_array_length", "json_each", "json_type", "json",
    # aggregate
    "avg", "count", "group_concat", "string_agg", "sum", "total",
    # date and time
    "date", "time", "datetime", "julianday", "strftime", "unixepoch", "timediff",
    # window
    "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "lag", "lead",
    "first_value", "last_value", "nth_value", "ntile",
    # math
    "sqrt", "pow", "power", "log", "log10", "log2", "ln", "exp", "floor", "ceil", "ceiling",
    "mod", "pi",
})


def _authorizer(denied: list[str], real: frozenset[str]):
    def check(action: int, arg1: str | None, arg2: str | None, _db: str | None,
              _source: str | None) -> int:
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            table = (arg1 or "").lower()
            if table in UNTRUSTED_TABLES or (table, (arg2 or "").lower()) in UNTRUSTED_COLUMNS:
                return sqlite3.SQLITE_IGNORE  # reads as NULL
            if table in ALLOWED_TABLES or (table not in real and table not in BLINDED):
                return sqlite3.SQLITE_OK  # a CTE's own name is not a stored table
            denied.append("blinded" if table in BLINDED else f"table {arg1}")
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            if (arg2 or "").lower() in ALLOWED_FUNCTIONS:
                return sqlite3.SQLITE_OK
            denied.append(f"function {arg2}")
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_RECURSIVE:
            return sqlite3.SQLITE_OK
        denied.append(f"action {action}")
        return sqlite3.SQLITE_DENY
    return check


def guarded_connect(path: Path) -> tuple[sqlite3.Connection, list[str]]:
    """A read-only connection and the list its authorizer appends refusal reasons to."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    denied: list[str] = []
    real = frozenset(r[0].lower() for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"))
    conn.set_authorizer(_authorizer(denied, real))
    deadline = time.monotonic() + TIME_LIMIT_S
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    return conn, denied


def explain(denied: list[str], exc: sqlite3.Error, query: str = "") -> str:
    # A query naming a blinded table can fail before the authorizer is asked (a bad JOIN);
    # it failed either way, so saying why leaks nothing.
    named = {w.lower() for w in re.findall(r"[A-Za-z_]+", query)} & BLINDED
    if "blinded" in denied or named:
        return ("the forecast ledger tables are blinded; use get_scoreboard for settled "
                "results")
    if denied:
        return f"refused by the read-only guard: {denied[0]}"
    if "interrupted" in str(exc).lower():
        return f"query interrupted after {TIME_LIMIT_S:g}s"
    return f"sqlite: {exc}"
