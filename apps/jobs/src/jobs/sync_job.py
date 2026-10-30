"""Cloud Run job: pull the database, migrate, sync, import the journal, push it back.

Each step logs one JSON line to stdout (`severity` INFO or ERROR, never health values);
the ERROR lines feed the failed-job alert. Exit 0 only if every step succeeded.

Step and push rules:

1. **pull** or **migrate** fails: stop. Nothing else runs, nothing is pushed.
2. **sync** fails with an auth error (`ReauthRequired` / `AuthError`): the journal step
   still runs (so a broken Forms token is reported too). Sync itself changed nothing, so
   only other completed work (journal, ledger) is pushed, under rule 6.
3. **sync** fails with a SQLite `DatabaseError` (a damaged or unreadable file): the journal
   step still runs, but nothing is pushed, so the good copy in the bucket survives.
4. **sync** raises any other exception (`SyncInterrupted`): the journal step still runs.
   Each data type finished before the exception committed atomically with its cursor, so
   the file is consistent, and the rows those types changed count toward rule 6.
5. A sync that completed with some failed data types, or a journal step that failed, still
   pushes the completed work.
6. The push is skipped when the run changed no data: no migration applied, zero
   new-or-changed rows from sync and zero new journal submissions. Bookkeeping alone
   (cursors, stage output, device inventory) is not worth a new bucket generation; the
   next run re-fetches the lookback anyway. So a network outage does not mint a new
   generation every run.
7. **lock** and **settle** (the forecast ledger) run after the journal step, unless the
   database errored (rule 3) or it is a dry run. Rows they write count as changed data.
   Their failure fails the run but never blocks pushing the other work.
8. **publish** (ledger bucket mirror, public date+hash log, scoreboard) runs only when the
   bucket holds this run's database: after a successful push, or when the push was
   skipped because nothing changed (then it retries whatever the destinations lack).
   Never after a failed push or a database error, so nothing public can describe a
   database state the bucket does not have.
9. **retest** and **investigate** (the agent layer, Phase 3) run after settle under the same
   gating as rule 7. Re-test re-judges live hypotheses on newly settled days (no model);
   the investigator studies the night's biggest miss within hard caps. An investigator that
   fails is logged as a WARNING and the job carries on (it records its own failed run);
   only an exception escaping either step, a code bug, fails the run. Rows they write
   (status rows, agent runs, receipts, hypotheses) count as changed data.

Every real run that got past migrate (not dry-run, synthetic or bucketless) then writes the
heartbeat beside the database: when it checked, whether it succeeded, whether it pushed,
and the last successful check. A skipped push leaves `sync_state` in the bucket older than
the last check, so the heartbeat is the freshness record. A heartbeat that cannot be
written fails the run.

Any failure exits non-zero. `--dry-run` works on a temp copy and never pushes. Journal
failures are logged as the error type and response id only.

Synthetic mode (`CHA_DATA_MODE=synthetic`) is the offline smoke test: it starts from an
empty local database, runs migrate, and logs sync, journal import and push as
"skipped (synthetic)". It needs no network and no credentials.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
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
    if name == "sync":
        from health_data.sync import SyncInterrupted, changed_rows

        if isinstance(exc, SyncInterrupted):  # log the real error and what was kept
            return {"error": type(exc.__cause__).__name__, "detail": str(exc.__cause__)[:300],
                    "committed_types": len(exc.summary), "changed_rows": changed_rows(exc.summary)}
    return {"error": type(exc).__name__, "detail": str(exc)[:300]}


def _step(name: str, fn: Callable[[], dict[str, Any] | None]) -> dict[str, Any]:
    from health_agents import tracing

    started = time.monotonic()
    # One span per step: name, duration and status only, never the step's output.
    with tracing.tracer().start_as_current_span(f"job.{name}") as span:
        span.set_attribute("cha.step", name)
        try:
            extra = fn() or {}
        except Exception as exc:
            span.set_status(tracing.error_status(type(exc).__name__))
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


def _lock(settings: Settings) -> dict[str, Any]:
    from health_data import civil
    from health_ledger import chain, lock

    with db.connect() as conn:
        chain.ensure_plan(conn, settings.analysis_plan_path)
        result = lock.lock_today(conn, civil.now())
    if result is None:
        return {"written": False, "result": "not due"}
    return {"written": True, **result}


def _settle() -> dict[str, Any]:
    from health_data import civil
    from health_ledger import outcomes

    with db.connect() as conn:
        counts = outcomes.settle(conn, civil.now())
    return {"written": any(counts.values()), **counts}


def _retest() -> dict[str, Any]:
    from health_agents import hypotheses
    from health_data import civil

    with db.connect() as conn:
        counts = hypotheses.retest(conn, civil.today())
    return counts


def _investigate() -> dict[str, Any]:
    from health_agents import investigator
    from health_data import civil

    with db.connect() as conn:
        out = investigator.run_investigation(conn, civil.now())
    return {k: v for k, v in out.items() if k != "covered"} | {"covered_days": len(out["covered"])}


def _agent_seq() -> tuple[int, int] | None:
    """Last rowids of the agent tables written by retest/investigate (None before v4)."""
    try:
        with db.connect() as conn:
            return (conn.execute("SELECT COALESCE(MAX(id), 0) FROM hypothesis_status").fetchone()[0],
                    conn.execute("SELECT COALESCE(MAX(id), 0) FROM agent_runs").fetchone()[0])
    except sqlite3.Error:
        return None


def _publish(settings: Settings) -> dict[str, Any]:
    from health_data import secrets
    from health_ledger import publish, scoreboard

    assert settings.ledger_bucket and settings.ledger_repo and settings.ledger_key_secret
    key = secrets.read_secret(settings.gcp_project, settings.ledger_key_secret)
    with db.connect() as conn:
        objects = publish.to_bucket(conn, settings.ledger_bucket)
        lines = publish.to_repo(conn, settings.ledger_repo, key, scoreboard.build(conn))
    return {"bucket_objects": objects, "repo_lines": lines}


def _ledger_seq() -> int | None:
    """The chain's last sequence number (None before schema v3 or on a read error)."""
    try:
        with db.connect() as conn:
            return conn.execute("SELECT MAX(seq) FROM ledger").fetchone()[0]
    except sqlite3.Error:
        return None


def _locked_today() -> bool:
    from health_data import civil

    try:
        with db.connect() as conn:
            return conn.execute("SELECT 1 FROM snapshots WHERE day = ?",
                                (civil.today().isoformat(),)).fetchone() is not None
    except sqlite3.Error:
        return False


def _heartbeat(bucket: str, obj: str, *, ok: bool, pushed: bool, generation: int | None,
               changed_rows: int, new_submissions: int) -> dict[str, Any]:
    checked_at = db.utc_stamp()
    last_ok_at: str | None = checked_at
    if not ok:
        try:  # carry the last good check forward; a missing or unreadable one is not fatal
            previous = store.read_heartbeat(bucket, obj) or {}
            last_ok_at = previous.get("last_ok_at")
        except Exception:
            last_ok_at = None
    beat = {"checked_at": checked_at, "ok": ok, "last_ok_at": last_ok_at, "pushed": pushed,
            "db_generation": generation, "changed_rows": changed_rows,
            "new_submissions": new_submissions, "locked_today": _locked_today()}
    store.write_heartbeat(bucket, obj, beat)
    return {"ok": ok, "pushed": pushed}


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

        from health_data.sync import SyncInterrupted, changed_rows

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

        if sync_result:
            sync_rows = sync_result["changed_rows"]
        elif isinstance(sync_error, SyncInterrupted):  # rule 4: only what was committed
            sync_rows = changed_rows(sync_error.summary)
        else:
            sync_rows = 0
        sync_cause = sync_error.__cause__ if isinstance(sync_error, SyncInterrupted) else sync_error
        new_submissions = int(journal_result.get("new_submissions", 0)) if journal_result else 0
        db_error = isinstance(sync_cause, sqlite3.DatabaseError)

        # rule 7. Whether the ledger changed is read from the database, not from step
        # results: a step that commits some rows and then raises still changed it.
        seq_before = None if db_error or dry_run else _ledger_seq()
        for name, fn in (("lock", lambda: _lock(settings)), ("settle", _settle)):
            if db_error:
                log(name, result="skipped (database error)")
            elif dry_run:
                log(name, result="skipped (dry-run)")
            else:
                try:
                    _step(name, fn)
                except _Abort:
                    failed = True
        ledger_written = not (db_error or dry_run) and _ledger_seq() != seq_before

        # rule 9
        agent_before = None if db_error or dry_run else _agent_seq()
        for name, fn in (("retest", _retest), ("investigate", _investigate)):
            if db_error:
                log(name, result="skipped (database error)")
            elif dry_run:
                log(name, result="skipped (dry-run)")
            else:
                try:
                    out = _step(name, fn)
                    if out.get("result") == "failed":
                        log(name, "WARNING", result="failed", error=out.get("error"))
                except _Abort:
                    failed = True
        agent_written = not (db_error or dry_run) and _agent_seq() != agent_before

        changed = (bool(migrated.get("migrated")) or bool(sync_rows) or bool(new_submissions)
                   or ledger_written or agent_written)
        generation = store.recorded_generation(generation_path)
        pushed = publishable = False
        if db_error:
            log("push", result="skipped (database error; the bucket copy is kept)")  # rule 3
        elif dry_run or not bucket:
            log("push", result="skipped (dry-run)" if dry_run else "skipped (CHA_DB_BUCKET not set)")
        elif not changed:
            # rule 6 (an auth failure lands here when nothing else changed: rule 2)
            log("push", result="skipped (no data changed)" if not isinstance(
                sync_error, auth.AuthError) else "skipped (sync auth failed; nothing else changed)")
            publishable = True
        else:
            try:
                generation = _step("push", lambda: {"generation": store.push_recorded(
                    bucket, settings.db_object, db.DB_PATH)})["generation"]
                pushed = publishable = True
            except _Abort:
                failed = True
        if dry_run or not bucket:
            return 1 if failed else 0
        if not (settings.ledger_bucket and settings.ledger_repo and settings.ledger_key_secret):
            log("publish", result="skipped (CHA_LEDGER_* not set)")
        elif not publishable:
            log("publish", result="skipped (database not in the bucket)")  # rule 8
        else:
            try:
                _step("publish", lambda: _publish(settings))
            except _Abort:
                failed = True
        try:
            _step("heartbeat", lambda: _heartbeat(
                bucket, settings.db_object, ok=not failed, pushed=pushed, generation=generation,
                changed_rows=sync_rows, new_submissions=new_submissions))
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
    from health_agents import tracing

    tracing.setup()  # CHA_TRACING=cloud in the job: Cloud Trace, content forced off
    with tracing.tracer().start_as_current_span("cha.job"):
        return _run(get_settings(), args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
