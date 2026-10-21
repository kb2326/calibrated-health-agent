"""Cloud Run job: pull the database, migrate, sync, import the journal, push it back.

Each step logs one JSON line to stdout (`severity` INFO or ERROR, never health values);
the ERROR lines feed the failed-job alert. Exit 0 only if every step succeeded.

Step and push rules:

1. **pull** or **migrate** fails: stop. Nothing else runs, nothing is pushed.
2. **sync** fails with an auth error (`ReauthRequired` / `AuthError`): the journal step
   still runs (so a broken Forms token is reported too), but nothing is pushed.
3. **sync** raises any other exception: the journal step still runs, and the database is
   pushed (pull and migrate succeeded; each data type sync finished before the exception
   committed atomically with its cursor, so the file is consistent).
4. A sync that completed with some failed data types, or a journal step that failed, still
   pushes the completed work.
5. The push is skipped when the run changed no data: no migration applied, zero
   new-or-changed rows from sync and zero new journal submissions. Bookkeeping alone
   (cursors, stage output, device inventory) is not worth a new bucket generation; the
   next run re-fetches the lookback anyway.

Any failure exits non-zero. `--dry-run` works on a temp copy and never pushes. Journal
failures are logged as the error type and response id only.

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
from health_data import auth, db, store

SKIPPED = "skipped (synthetic)"


def log(step: str, severity: str = "INFO", **fields: Any) -> None:
    print(json.dumps({"severity": severity, "step": step, **fields}, default=str), flush=True)


class _Abort(Exception):
    """A step failed; `__cause__` is the original exception."""


def _error_fields(name: str, exc: BaseException) -> dict[str, Any]:
    if name == "journal":  # answers must never reach a log line: type + response id only
        from health_data.journal_import import describe_error

        return describe_error(exc)
    return {"error": type(exc).__name__, "detail": str(exc)[:300]}


def _step(name: str, fn: Callable[[], dict[str, Any] | None]) -> dict[str, Any]:
    started = time.monotonic()
    try:
        extra = fn() or {}
    except Exception as exc:
        log(name, "ERROR", **_error_fields(name, exc))
        raise _Abort from exc
    log(name, "INFO", seconds=round(time.monotonic() - started, 2), **extra)
    return extra


def _migrate() -> dict[str, Any]:
    with db.connect() as conn:
        before = conn.execute("PRAGMA user_version").fetchone()[0]
        after = db.migrate(conn)
    return {"schema_version": after, "migrated": after != before}


def _sync() -> dict[str, Any]:
    from health_data import sync

    summary = sync.run()
    if not summary:
        raise RuntimeError("sync returned an empty summary; nothing was synced")
    failed = sync.failed_types(summary)
    types = [t for t in summary if not t.startswith("_")]
    return {"types_ok": len(types) - len(failed), "types_failed": len(failed), "failed": failed,
            "changed_rows": sync.changed_rows(summary), "exit_code": sync.exit_code(summary)}


def _journal_import(settings: Settings) -> dict[str, Any]:
    from health_data.journal_import import append_submissions, fetch_responses, parse_responses

    if not settings.journal_form_id:
        return {"result": "skipped (CHA_JOURNAL_FORM_ID not set)", "new_submissions": 0}
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
    saved_db_path = db.DB_PATH
    if dry_run or synthetic:
        # A temp copy: nothing local or remote is touched, and nothing is ever pushed.
        tmp = tempfile.TemporaryDirectory(prefix="sync-job-")
        db.DB_PATH = Path(tmp.name) / "health.db"
        generation_path = Path(tmp.name) / ".db_generation"
    try:
        try:
            if synthetic or not bucket:
                log("pull", result=SKIPPED if synthetic else "skipped (CHA_DB_BUCKET not set)")
            else:
                _step("pull", lambda: {"generation": store.pull_db(bucket, settings.db_object, db.DB_PATH, gen_path=generation_path)})
            migrated = _step("migrate", _migrate)
        except _Abort:
            return 1  # rule 1
        if synthetic:
            for name in ("sync", "journal", "push"):
                log(name, result=SKIPPED)
            return 0

        sync_result: dict[str, Any] | None = None
        sync_error: BaseException | None = None
        try:
            sync_result = _step("sync", _sync)
        except _Abort as exc:
            sync_error = exc.__cause__
        journal_result: dict[str, Any] | None = None
        try:
            journal_result = _step("journal", lambda: _journal_import(settings))
        except _Abort:
            pass
        if sync_result and sync_result["types_failed"]:
            log("sync", "ERROR", error="partial sync", failed=sync_result["failed"])
        failed = (sync_error is not None or journal_result is None
                  or bool(sync_result and sync_result["types_failed"]))

        changed = (
            bool(migrated.get("migrated"))
            or sync_error is not None  # rule 3: unknown how much was committed; push it
            or bool(sync_result and sync_result["changed_rows"])
            or bool(journal_result and journal_result.get("new_submissions"))
        )
        if isinstance(sync_error, auth.AuthError):
            log("push", result="skipped (sync auth failed; re-login needed)")  # rule 2
        elif dry_run or not bucket:
            log("push", result="skipped (dry-run)" if dry_run else "skipped (CHA_DB_BUCKET not set)")
        elif not changed:
            log("push", result="skipped (no data changed)")  # rule 5
        else:
            try:
                _step("push", lambda: {"generation": store.push_recorded(bucket, settings.db_object, db.DB_PATH)})
            except _Abort:
                return 1
        return 1 if failed else 0
    finally:
        db.DB_PATH = saved_db_path
        if tmp is not None:
            tmp.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sync-job", description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="run every step on a temp copy; never push")
    args = parser.parse_args(argv)
    return _run(get_settings(), args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
