"""`cha-data`: data-layer commands. Never prints answer values."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import typer
from health_core.settings import get_settings

from health_data import db

app = typer.Typer(pretty_exceptions_show_locals=False, no_args_is_help=True, help="Calibrated Health Agent data commands.")
journal_app = typer.Typer(pretty_exceptions_show_locals=False, no_args_is_help=True, help="Daily journal (Google Form).")
db_app = typer.Typer(pretty_exceptions_show_locals=False, no_args_is_help=True, help="Local database maintenance.")
auth_app = typer.Typer(pretty_exceptions_show_locals=False, no_args_is_help=True, help="Google Health authorization.")
app.add_typer(journal_app, name="journal")
app.add_typer(db_app, name="db")
app.add_typer(auth_app, name="auth")


def _auth_guard(fn):
    """Run `fn`; an AuthError becomes a one-line message and exit 1 (no traceback)."""
    from health_data import auth

    try:
        return fn()
    except auth.AuthError as exc:
        typer.echo(f"auth error: {exc}", err=True)
        raise typer.Exit(1) from None


@app.command("sync")
def sync_cmd() -> None:
    """Incremental sync of every tracked type; prints counts only. Exit 1 on any failure."""
    from health_data import sync

    summary = _auth_guard(sync.run)
    failed = [t for t, v in summary.items() if "error" in v]
    typer.echo(f"done: {len(summary) - len(failed)} ok, {len(failed)} failed")
    raise typer.Exit(sync.exit_code(summary))


@app.command("backfill")
def backfill_cmd(
    since: Annotated[datetime, typer.Option("--since", formats=["%Y-%m-%d"], help="First day to cover, YYYY-MM-DD.")],
    types: Annotated[list[str] | None, typer.Option("--type", help="Restrict to these data types (repeatable).")] = None,
) -> None:
    """Resumable history backfill over [since, today); prints inserted counts per type."""
    from health_data import backfill as bf

    start = since.date()
    if start > datetime.now(UTC).date() + timedelta(days=1):
        typer.echo("--since is in the future", err=True)
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
    """Count what each readable type returns over the last N days."""
    from health_data import sync

    counts = _auth_guard(lambda: sync.probe(days))
    for data_type, n in counts.items():
        typer.echo(f"{data_type:40s} {n:7d}")


@app.command("parity")
def parity_cmd(days: Annotated[int, typer.Option("--days", min=1)] = 30) -> None:
    """Rollup-vs-reconcile agreement per summed type over the last N days (counts only)."""
    from health_data import reconcile

    end = datetime.now(UTC).date()
    start: date = end - timedelta(days=days)
    for data_type in sorted(reconcile.SUMMED_TYPES):
        if data_type in reconcile.RECONCILE_UNSUPPORTED:
            typer.echo(f"{data_type:30s} reconcile unsupported")
            continue
        rows = _auth_guard(lambda dt=data_type: reconcile.parity_report(dt, start, end))
        agree, worn = reconcile.parity_summary(rows)
        typer.echo(f"{data_type:30s} worn days={worn:4d}  agree={agree:4d}")


@db_app.command("vacuum")
def db_vacuum_cmd() -> None:
    """VACUUM the local database and report its size."""
    before, after = db.vacuum(db.DB_PATH)
    typer.echo(f"vacuumed: {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB")


@db_app.command("migrate")
def db_migrate_cmd() -> None:
    """Apply pending schema migrations."""
    db.init_db()
    with db.connect() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    typer.echo(f"schema version: {version}")


@auth_app.command("login")
def auth_login_cmd() -> None:
    """Authorize against Google (opens a browser for consent)."""
    from health_data import auth

    _auth_guard(auth._cli_login)


@auth_app.command("status")
def auth_status_cmd() -> None:
    """Show token validity, granted scopes and any scope gap."""
    from health_data import auth

    _auth_guard(auth._cli_status)


@journal_app.command("import")
def journal_import_cmd() -> None:
    """Import Form responses into the append-only journal; prints status counts only."""
    from health_data.journal_import import append_submissions, fetch_responses, parse_responses

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
        typer.echo(f"journal import failed: {type(exc).__name__}", err=True)
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
