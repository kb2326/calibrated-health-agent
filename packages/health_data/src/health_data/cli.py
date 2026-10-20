"""`cha-data`: data-layer commands. Never prints answer values."""
from __future__ import annotations

import typer
from health_core.settings import get_settings

from health_data import db

app = typer.Typer(no_args_is_help=True, help="Calibrated Health Agent data commands.")
journal_app = typer.Typer(no_args_is_help=True, help="Daily journal (Google Form).")
app.add_typer(journal_app, name="journal")


@journal_app.command("import")
def journal_import_cmd() -> None:
    """Import Form responses into the append-only journal; prints status counts only."""
    from health_data.journal_import import append_submissions, fetch_responses, parse_responses

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


@journal_app.command("create-form")
def create_form_cmd() -> None:
    """Create the daily journal Google Form (one-off; opens a browser for consent)."""
    from health_data.journal_form import create_form

    info = create_form()
    typer.echo(f"FORM_ID {info['form_id']}")
    typer.echo(f"PHONE_LINK {info['phone_link']}")
    typer.echo(f"EDIT_LINK {info['edit_link']}")
    typer.echo(f"Set CHA_JOURNAL_FORM_ID={info['form_id']} in .env")
