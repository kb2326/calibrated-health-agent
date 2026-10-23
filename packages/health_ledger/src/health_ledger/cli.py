"""`cha-ledger`: inspect the forecast ledger without unblinding it.

Every command reads the local database (pull it first with `cha-data db pull`). None
prints a probability or an unsettled bet: status shows counts and the chain check,
scoreboard prints the same aggregates the public page shows.
"""
from __future__ import annotations

import json

import typer
from health_data import db

from health_ledger import associations, chain, scoreboard

app = typer.Typer(help=__doc__, no_args_is_help=True)


@app.command()
def status() -> None:
    """Days locked and settled, and whether the hash chain verifies."""
    with db.connect() as conn:
        board = scoreboard.build(conn)
        problems = chain.verify(conn)
    typer.echo(f"days locked: {board['days_locked']}")
    typer.echo(f"days scored: {board['days_scored']}  void: {board['days_voided']}  "
               f"no journal: {board['days_no_outcome']}")
    typer.echo("chain: ok" if not problems else f"chain: {len(problems)} problem(s)")


@app.command()
def verify() -> None:
    """Recompute every chain hash; exit 1 on any break."""
    with db.connect() as conn:
        problems = chain.verify(conn)
    for problem in problems:
        typer.echo(problem, err=True)
    raise typer.Exit(1 if problems else 0)


@app.command("scoreboard")
def scoreboard_cmd() -> None:
    """Print the aggregate scoreboard as JSON (settled days only)."""
    with db.connect() as conn:
        typer.echo(json.dumps(scoreboard.build(conn), indent=1))


@app.command("associations")
def associations_cmd(min_n: int = 10) -> None:
    """BH-corrected associations between wearable metrics and journal outcomes."""
    with db.connect() as conn:
        rows = associations.run(conn, min_n=min_n)
    if not rows:
        typer.echo(f"no metric-target pair has n >= {min_n} yet")
    for r in rows:
        typer.echo(f"{r['metric']:30s} {r['target']:9s} lag {r['lag']}  rho {r['rho']:+.2f}  "
                   f"n {r['n']:3d}  q {r['q']:.3f}  (association, not cause)")
