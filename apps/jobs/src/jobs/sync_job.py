"""Cloud Run job: pull the database, migrate, sync, import the journal, push it back.

Each step logs one JSON line to stdout (`severity` INFO or ERROR, never health values);
the ERROR lines feed the failed-job alert. Exit 0 only if every step succeeded.

Push rules (same as the CLI guard): a sync that completed with some failed data types is
still pushed (completed work is never lost) and the job exits non-zero; an exception or a
reauth failure in pull, migrate or sync means no push, while a journal-import failure after a
completed sync still pushes the sync work (and exits non-zero). `--dry-run` works on a temp copy and never pushes.

Synthetic mode (`CHA_DATA_MODE=synthetic`) is the offline smoke test: it starts from an
empty local database, runs migrate, and logs sync, journal import and push as
"skipped (synthetic)". It needs no network and no credentials.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from health_core.settings import Settings, get_settings
from health_data import db, store

SKIPPED = "skipped (synthetic)"


def log(step: str, severity: str = "INFO", **fields: Any) -> None:
    print(json.dumps({"severity": severity, "step": step, **fields}, default=str), flush=True)


class _Abort(Exception):
    """A step failed in a way that forbids pushing."""


def _step(name: str, fn: Callable[[], dict[str, Any] | None]) -> dict[str, Any]:
    started = time.monotonic()
    try:
        extra = fn() or {}
    except Exception as exc:  # message only: exceptions here never carry health values
        log(name, "ERROR", error=type(exc).__name__, detail=str(exc)[:300])
        raise _Abort from exc
    log(name, "INFO", seconds=round(time.monotonic() - started, 2), **extra)
    return extra


def _migrate() -> dict[str, Any]:
    with db.connect() as conn:
        return {"schema_version": db.migrate(conn)}


def _sync() -> dict[str, Any]:
    from health_data import sync

    summary = sync.run()
    if not summary:
        raise RuntimeError("sync returned an empty summary; nothing was synced")
    failed = sorted(t for t, v in summary.items() if "error" in v)
    return {"types_ok": len(summary) - len(failed), "types_failed": len(failed), "failed": failed,
            "exit_code": sync.exit_code(summary)}


def _journal_import(settings: Settings) -> dict[str, Any]:
    from health_data.journal_import import append_submissions, fetch_responses, parse_responses

    if not settings.journal_form_id:
        return {"result": "skipped (CHA_JOURNAL_FORM_ID not set)"}
    question_ids, responses = fetch_responses(settings.journal_form_id)
    rows, problems = parse_responses(question_ids, responses, settings.timezone)
    db.init_db()
    with db.connect() as conn:
        counts = append_submissions(conn, rows)
    return {"responses": len(responses), "new_submissions": sum(counts.values()), "invalid": len(problems)}


def _run(settings: Settings, dry_run: bool) -> int:
    synthetic = settings.data_mode == "synthetic"
    bucket = settings.db_bucket
    generation_path: Path | None = None
    tmp: tempfile.TemporaryDirectory[str] | None = None
    if dry_run or synthetic:
        # A temp copy: nothing local or remote is touched, and nothing is ever pushed.
        tmp = tempfile.TemporaryDirectory(prefix="sync-job-")
        db.DB_PATH = Path(tmp.name) / "health.db"
        generation_path = Path(tmp.name) / ".db_generation"
    try:
        if synthetic or not bucket:
            log("pull", result=SKIPPED if synthetic else "skipped (CHA_DB_BUCKET not set)")
        else:
            _step("pull", lambda: {"generation": store.pull_db(bucket, settings.db_object, db.DB_PATH, gen_path=generation_path)})
        _step("migrate", _migrate)
        if synthetic:
            for name in ("sync", "journal", "push"):
                log(name, result=SKIPPED)
            return 0
        sync_result = _step("sync", _sync)
        # A journal failure must not discard the completed sync: still push, exit 1.
        journal_failed = False
        try:
            _step("journal", lambda: _journal_import(settings))
        except _Abort:
            journal_failed = True
        if sync_result["types_failed"]:
            log("sync", "ERROR", error="partial sync", failed=sync_result["failed"])
        failed = bool(sync_result["types_failed"]) or journal_failed
        if dry_run or not bucket:
            log("push", result="skipped (dry-run)" if dry_run else "skipped (CHA_DB_BUCKET not set)")
        else:
            _step("push", lambda: {"generation": store.push_recorded(bucket, settings.db_object, db.DB_PATH)})
        return 1 if failed else 0
    except _Abort:
        return 1
    finally:
        if tmp is not None:
            tmp.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sync-job", description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="run every step on a temp copy; never push")
    args = parser.parse_args(argv)
    return _run(get_settings(), args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
