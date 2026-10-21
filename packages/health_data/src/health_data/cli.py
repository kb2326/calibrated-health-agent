"""`cha-data`: data-layer commands. Never prints answer values.

Write guard (GCS is the source of truth). With `CHA_DATA_MODE=real` every command that
writes the database (sync, backfill, journal import, db migrate/vacuum/repair) needs
`CHA_DB_BUCKET`: it refuses on a stale local copy and pushes after a run that wrote. Without
the bucket it refuses, unless the global `--local-only` flag is given: then it writes the
local file only and never pushes (a scratch copy for development; a later `db pull` will
refuse to overwrite it without `--force`). Synthetic mode never needs the bucket.
"""
from __future__ import annotations

import functools
import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer
from health_core.settings import get_settings

from health_data import civil, db, store

app = typer.Typer(pretty_exceptions_show_locals=False, no_args_is_help=True, help="Calibrated Health Agent data commands.")
journal_app = typer.Typer(pretty_exceptions_show_locals=False, no_args_is_help=True, help="Daily journal (Google Form).")
db_app = typer.Typer(pretty_exceptions_show_locals=False, no_args_is_help=True, help="Local database maintenance.")
auth_app = typer.Typer(pretty_exceptions_show_locals=False, no_args_is_help=True, help="Google Health authorization.")
app.add_typer(journal_app, name="journal")
app.add_typer(db_app, name="db")
app.add_typer(auth_app, name="auth")

_STATE = {"local_only": False}

NEEDS_BUCKET = (
    "CHA_DB_BUCKET is not set. With CHA_DATA_MODE=real, commands that write the database need "
    "the bucket (GCS is the source of truth): set CHA_DB_BUCKET and run `cha-data db pull` "
    "first. To write a local scratch copy that is never pushed, pass --local-only "
    "(`cha-data --local-only <command>`)."
)


@app.callback()
def _main(
    local_only: Annotated[bool, typer.Option(
        "--local-only",
        help="Write the local database only, without CHA_DB_BUCKET; never pushes (dev/scratch).",
    )] = False,
) -> None:
    _STATE["local_only"] = local_only


def _auth_guard(fn):
    """Run `fn`; an AuthError becomes a one-line message and exit 1 (no traceback)."""
    from health_data import auth

    try:
        return fn()
    except auth.AuthError as exc:
        typer.echo(f"auth error: {exc}", err=True)
        raise typer.Exit(1) from None


def _db_fingerprint() -> tuple[str | None, ...]:
    """sha256 of the db file and its -wal (None if absent); a change means the command wrote.

    Content, not size/mtime: a same-size write inside one filesystem timestamp tick must
    still be detected, or it would silently never be pushed.
    """
    out: list[str | None] = []
    for suffix in ("", "-wal"):
        path = Path(str(db.DB_PATH) + suffix)
        if not path.exists():
            out.append(None)
            continue
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            while chunk := fh.read(1 << 20):
                digest.update(chunk)
        out.append(digest.hexdigest())
    return tuple(out)


def _run_persisted(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a writing command under the write guard (module docstring).

    A run that completes and wrote to the db is pushed even when it ends in a nonzero
    typer.Exit (e.g. a partial sync), so successful work is never lost to a later pull;
    the same exit code is then re-raised. Any other exception, or a run that left the db
    file unchanged (e.g. auth error before writing), does not push. "Wrote" is detected
    by a content-hash change of the db file or its -wal.
    """
    settings = get_settings()
    bucket = settings.db_bucket
    try:
        if not bucket:
            if settings.data_mode == "real" and not _STATE["local_only"]:
                typer.echo(NEEDS_BUCKET, err=True)
                raise typer.Exit(1)
            return fn(*args, **kwargs)
        pending: typer.Exit | None = None
        result = None
        try:
            store.require_fresh(bucket, settings.db_object)
            before = _db_fingerprint()
            try:
                result = fn(*args, **kwargs)
            except typer.Exit as exc:
                pending = exc
            if _db_fingerprint() != before:
                try:
                    store.push_recorded(bucket, settings.db_object, db.DB_PATH)
                except store.ConcurrentUpdateError:
                    raise  # handled below with its own message
                except (RuntimeError, FileNotFoundError) as exc:  # busy checkpoint, missing source
                    typer.echo(f"db error: {type(exc).__name__}: {exc}", err=True)
                    raise typer.Exit(1) from None
        except (store.StaleLocalDbError, store.ConcurrentUpdateError) as exc:
            typer.echo(f"db error: {exc}", err=True)
            raise typer.Exit(1) from None
        if pending is not None:
            raise pending
        return result
    except db.SchemaTooNewError as exc:
        typer.echo(f"db error: {exc}", err=True)
        raise typer.Exit(1) from None


def _persisted(fn):
    """Decorator form of `_run_persisted` for writing commands."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return _run_persisted(fn, *args, **kwargs)

    return wrapper


@app.command("sync")
@_persisted
def sync_cmd() -> None:
    """Sync every tracked type (lookback + today, owner zone); prints counts only. Exit 1 on any failure."""
    from health_data import sync

    summary = _auth_guard(sync.run)
    failed = sync.failed_types(summary)
    typer.echo(f"done: {len(summary) - len(failed)} ok, {len(failed)} failed")
    raise typer.Exit(sync.exit_code(summary))


@app.command("backfill")
@_persisted
def backfill_cmd(
    since: Annotated[datetime, typer.Option("--since", formats=["%Y-%m-%d"], help="First owner-zone day to cover, YYYY-MM-DD.")],
    types: Annotated[list[str] | None, typer.Option("--type", help="Restrict to these data types (repeatable).")] = None,
) -> None:
    """Resumable history backfill over [since, today) in owner-zone days; prints changed counts per type."""
    from health_data import backfill as bf

    start = since.date()
    if start > civil.today():
        typer.echo("--since is in the future (owner time zone)", err=True)
        raise typer.Exit(2)
    failed = False
    try:
        inserted = _auth_guard(lambda: bf.backfill(start, types or None))
    except bf.BackfillError as exc:
        inserted, failed = exc.inserted, True
        for data_type, message in sorted(exc.errors.items()):
            typer.echo(f"{data_type:30s} FAILED {message}", err=True)
    typer.echo(f"backfill covers {start.isoformat()} onward (today excluded)")
    for data_type, n in inserted.items():
        typer.echo(f"{data_type:30s} inserted={n:7d}")
    typer.echo(f"total inserted: {sum(inserted.values())}")
    if failed:
        typer.echo("incomplete: rerun the same command to resume", err=True)
        raise typer.Exit(1)


@app.command("probe")
def probe_cmd(days: Annotated[int, typer.Option("--days", min=1)] = 30) -> None:
    """Count what each readable type returns over the last N owner-zone days."""
    from health_data import sync

    counts = _auth_guard(lambda: sync.probe(days))
    for data_type, n in counts.items():
        typer.echo(f"{data_type:40s} {n:7d}")


@app.command("parity")
def parity_cmd(days: Annotated[int, typer.Option("--days", min=1)] = 30) -> None:
    """Rollup-vs-reconcile agreement per summed type over the last N owner-zone days (counts only)."""
    from health_data import reconcile

    end = civil.today()
    start = end - timedelta(days=days)
    for data_type in sorted(reconcile.SUMMED_TYPES):
        if data_type in reconcile.RECONCILE_UNSUPPORTED:
            typer.echo(f"{data_type:30s} reconcile unsupported")
            continue
        rows = _auth_guard(lambda dt=data_type: reconcile.parity_report(dt, start, end))
        agree, worn = reconcile.parity_summary(rows)
        typer.echo(f"{data_type:30s} worn days={worn:4d}  agree={agree:4d}")


@db_app.command("vacuum")
@_persisted
def db_vacuum_cmd() -> None:
    """VACUUM the local database and report its size."""
    before, after = db.vacuum(db.DB_PATH)
    typer.echo(f"vacuumed: {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB")


@db_app.command("migrate")
@_persisted
def db_migrate_cmd() -> None:
    """Apply pending schema migrations."""
    db.init_db()
    with db.connect() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    typer.echo(f"schema version: {version}")


def _print_repair(report: dict[str, dict[str, Any]]) -> bool:
    """Counts and day ranges only. Returns True if any type failed."""
    failed = False
    for data_type, r in report.items():
        b = r["before"]
        if "error" in r:
            failed = True
            typer.echo(f"{data_type:36s} FAILED {r['error']}", err=True)
            continue
        a = r["after"]
        typer.echo(
            f"{data_type:36s} days {b['days']:4d} [{b['first']}..{b['last']}] -> "
            f"{a['days']:4d} [{a['first']}..{a['last']}]  raw {b['raw_rows']} -> {a['raw_rows']}  "
            f"fetched={r['fetched']} changed={r['changed']}"
        )
    return failed


@db_app.command("repair")
def db_repair_cmd(
    days: Annotated[int | None, typer.Option("--days", min=1, help="Only the last N owner-zone days (default: full history).")] = None,
    types: Annotated[list[str] | None, typer.Option("--type", help="Restrict to these data types (repeatable).")] = None,
    db_file: Annotated[Path | None, typer.Option("--db", help="Repair this file instead; local only, never pushed.")] = None,
) -> None:
    """Re-fetch history and recompute daily values under the owner-zone civil-day rule."""
    from health_data import repair

    def run() -> None:
        try:
            report = _auth_guard(lambda: repair.repair(days, types or None))
        except db.SchemaTooNewError as exc:
            typer.echo(f"db error: {exc}", err=True)
            raise typer.Exit(1) from None
        if _print_repair(report):
            typer.echo("incomplete: rerun to retry the failed types", err=True)
            raise typer.Exit(1)

    if db_file is None:
        _run_persisted(run)
        return
    if not db_file.exists():
        typer.echo(f"{db_file} does not exist", err=True)
        raise typer.Exit(2)
    saved = db.DB_PATH
    db.DB_PATH = db_file
    try:
        run()
    finally:
        db.DB_PATH = saved


def _require_bucket() -> tuple[str, str]:
    settings = get_settings()
    if not settings.db_bucket:
        typer.echo("CHA_DB_BUCKET is not set", err=True)
        raise typer.Exit(1)
    return settings.db_bucket, settings.db_object


@db_app.command("pull")
def db_pull_cmd(
    force: Annotated[bool, typer.Option("--force", help="Overwrite a local database with unpushed changes.")] = False,
) -> None:
    """Download the bucket database (source of truth) and record its generation.

    Refuses when the local file changed since it was last pulled or pushed (unpushed work),
    unless --force.
    """
    bucket, obj = _require_bucket()
    if not force:
        try:
            store.check_pull_safe(db.DB_PATH)
        except store.LocalChangesError as exc:
            typer.echo(f"db error: {exc}", err=True)
            raise typer.Exit(1) from None
    generation = store.pull_db(bucket, obj, db.DB_PATH)
    typer.echo("no remote database yet" if generation is None else f"pulled generation {generation}")


@db_app.command("push")
def db_push_cmd() -> None:
    """Upload the local database, conditional on the recorded generation."""
    bucket, obj = _require_bucket()
    try:
        generation = store.push_recorded(bucket, obj, db.DB_PATH)
    except store.ConcurrentUpdateError as exc:
        typer.echo(f"db error: {exc}", err=True)
        raise typer.Exit(1) from None
    except (RuntimeError, FileNotFoundError) as exc:
        typer.echo(f"db error: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"pushed generation {generation}")


@auth_app.command("login")
def auth_login_cmd() -> None:
    """Authorize the Health token (Health read-only scopes only; opens a browser)."""
    from health_data import auth

    _auth_guard(auth._cli_login)


@auth_app.command("login-forms")
def auth_login_forms_cmd() -> None:
    """Authorize the separate Forms token (journal import; opens a browser)."""
    from health_data import auth

    _auth_guard(auth._cli_login_forms)


@auth_app.command("push-secret")
def auth_push_secret_cmd() -> None:
    """Upload the OAuth client, Health token and Forms token to Secret Manager."""
    from health_data import auth

    _auth_guard(auth.push_secrets)


@auth_app.command("status")
def auth_status_cmd() -> None:
    """Show granted vs expected scopes for the Health and Forms tokens."""
    from health_data import auth

    _auth_guard(auth._cli_status)


@journal_app.command("import")
@_persisted
def journal_import_cmd() -> None:
    """Import Form responses into the append-only journal; prints status counts only."""
    from health_data.journal_import import (
        append_submissions,
        describe_error,
        fetch_responses,
        parse_responses,
    )

    try:
        settings = get_settings()
        if not settings.journal_form_id:
            typer.echo("CHA_JOURNAL_FORM_ID is not set", err=True)
            raise typer.Exit(1)
        question_ids, responses = fetch_responses(settings.journal_form_id)
        rows, problems = parse_responses(question_ids, responses, settings.timezone)
        db.init_db()
        with db.connect() as conn:
            before = {d for (d,) in conn.execute("SELECT DISTINCT date FROM journal_submissions")}
            counts = append_submissions(conn, rows)
        new = sum(counts.values())
        typer.echo(f"responses fetched: {len(responses)}")
        typer.echo(f"new submissions: {new}")
        for status in ("ok", "late", "edited", "invalid"):
            if counts.get(status):
                typer.echo(f"  {status}: {counts[status]}")
        kept = counts.get("ok", 0) - len({r.date for r in rows if r.status == "ok"} - before)
        if kept > 0:
            typer.echo(f"{kept} kept as later submissions (earliest ok per date stays the outcome)")
        for problem in problems:
            typer.echo(f"invalid: {problem}")
    except typer.Exit:
        raise
    except Exception as exc:  # never let a traceback (with locals) carry answer values
        info = describe_error(exc)
        typer.echo(f"journal import failed: {info['error']} (response_id={info['response_id']})", err=True)
        raise typer.Exit(1) from None


@journal_app.command("create-form")
def create_form_cmd() -> None:
    """Create the daily journal Google Form (one-off; opens a browser for consent)."""
    from health_data.journal_form import create_form

    info = create_form()
    typer.echo(f"FORM_ID {info['form_id']}")
    typer.echo(f"PHONE_LINK {info['phone_link']}")
    typer.echo(f"EDIT_LINK {info['edit_link']}")
    typer.echo(f"Set CHA_JOURNAL_FORM_ID={info['form_id']} in .env")
