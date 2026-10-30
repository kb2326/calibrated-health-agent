"""`cha-eval`: build, run, review and report the agent's evals (Phase 4).

    cha-eval questions --n 120 [--draft]     question batch for error analysis
    cha-eval build                           ADK evalsets from evals/cases/*.yaml

Synthetic runs use the model configured in the environment (CI: a free-tier AI Studio key);
real-data runs are laptop-only and write under data/evals/.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from . import cases, questions, review

app = typer.Typer(add_completion=False, help="Evals for the Calibrated Health Agent.")


def _generate(prompt: str) -> str:
    from google import genai
    from health_core.settings import get_settings

    client = genai.Client()  # environment decides: AI Studio key in CI, Vertex on the laptop
    return client.models.generate_content(model=get_settings().model_default, contents=prompt).text or ""


@app.command("questions")
def questions_cmd(n: Annotated[int, typer.Option("--n")] = 120,
                  draft: Annotated[bool, typer.Option("--draft")] = False,
                  out: Annotated[Path | None, typer.Option("--out")] = None) -> None:
    """Write a batch of grid questions (optionally paraphrased by the model)."""
    items = questions.expand(questions.load_grid(), n)
    if draft:
        items = questions.paraphrase(items, _generate)
    path = questions.write_batch(items, out or Path(f"evals/questions/batch-{date.today()}.yaml"))
    typer.echo(f"{len(items)} questions -> {path}")


@app.command("build")
def build_cmd() -> None:
    """Generate ADK evalsets from the YAML cases."""
    for path in cases.write_evalsets():
        typer.echo(f"wrote {path}")


@app.command("review")
def review_cmd(file: Path,
               port: Annotated[int, typer.Option("--port")] = review.PORT) -> None:
    """Label transcripts Pass / Fail on a local page (127.0.0.1 only)."""
    review.serve(file, port)
