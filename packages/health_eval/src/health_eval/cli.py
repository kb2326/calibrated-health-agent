"""`cha-eval`: build, run, review and report the agent's evals (Phase 4).

    cha-eval questions --n 120 [--draft]     question batch for error analysis
    cha-eval build                           ADK evalsets from evals/cases/*.yaml

Synthetic runs use the model configured in the environment (CI: a free-tier AI Studio key);
real-data runs are laptop-only and write under data/evals/.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
import yaml

from . import ablation, adk_eval, cases, questions, redteam, report, review, runner

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


@app.command("ablation")
def ablation_cmd(suite: Annotated[str, typer.Option("--suite")] = "ablation",
                 trials: Annotated[int, typer.Option("--trials")] = 1,
                 out_dir: Annotated[Path, typer.Option("--out-dir")] = Path("data/evals/ablation"),
                 limit: Annotated[int, typer.Option("--limit")] = 0) -> None:
    """Run the four ablation arms on the synthetic fixture (live model: 4 x cases x trials turns)."""
    chosen = cases.load_cases(suite)
    result = ablation.run_ablation(chosen[:limit] if limit else chosen, trials=trials,
                                   out_dir=out_dir)
    for arm, s in result["arms"].items():
        typer.echo(f"{arm:9} {s['k']}/{s['n']}  ci {s['ci'][0]:.2f}-{s['ci'][1]:.2f}")
    for name, c in result["comparisons"].items():
        typer.echo(f"{name:17} b={c['b']} c={c['c']} p={c['p_mcnemar']:.3f} "
                   f"diff={c['diff']:+.2f} mdd={c['mdd'] or 0:.2f}")


def select_cases(suites: list[str], *, must_pass_only: bool = False, rotate: int = 0,
                 day: int | None = None, limit: int = 0) -> list[cases.Case]:
    """Cases from `suites`; `rotate=N` takes a day-dependent window of N (nightly slices that
    cover every case over a few days within the free tier's daily request limit)."""
    chosen = [c for s in suites for c in cases.load_cases(s)]
    if must_pass_only:
        chosen = [c for c in chosen if c.expect.must_pass]
    if rotate and len(chosen) > rotate:
        start = ((date.today().timetuple().tm_yday if day is None else day) * rotate) % len(chosen)
        chosen = (chosen + chosen)[start:start + rotate]
    return chosen[:limit] if limit else chosen


@app.command("run")
def run_cmd(suite: Annotated[list[str], typer.Option("--suite")],
            trials: Annotated[int, typer.Option("--trials")] = 1,
            limit: Annotated[int, typer.Option("--limit")] = 0,
            must_pass_only: Annotated[bool, typer.Option("--must-pass-only")] = False,
            rotate: Annotated[int, typer.Option("--rotate")] = 0,
            pace: Annotated[float, typer.Option("--pace", help="seconds between cases")] = 0,
            out_dir: Annotated[Path, typer.Option("--out-dir")] = Path("data/evals/runs")) -> None:
    """Run and grade suites on the synthetic fixture; writes transcripts and summary.json."""
    chosen = select_cases(suite, must_pass_only=must_pass_only, rotate=rotate, limit=limit)
    stamp = date.today().isoformat()
    transcripts, verdicts = report.run_suite(chosen, trials=trials, pace_s=pace,
                                             out=out_dir / f"{stamp}-transcripts.jsonl")
    rt = redteam.asr(transcripts, verdicts) if any(c.suite == "redteam" for c in chosen) else None
    summary = report.summarise(transcripts, chosen, verdicts, {}, redteam=rt)
    path = out_dir / "summary.json"
    path.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    typer.echo(report.readme_block(summary))
    typer.echo(f"summary: {path}")


@app.command("report")
def report_cmd(summary: Path,
               out: Annotated[Path, typer.Option("--out")] = report.RESULTS,
               readme: Annotated[Path | None, typer.Option("--readme")] = None) -> None:
    """Write docs/evals/results/<date>-<sha>.md from a summary; optionally refresh README."""
    data = json.loads(summary.read_text(encoding="utf-8"))
    typer.echo(f"wrote {report.write_results(data, out)}")
    if readme:
        readme.write_text(report.replace_readme_block(readme.read_text(encoding="utf-8"),
                                                      report.readme_block(data)), encoding="utf-8")
        typer.echo(f"updated {readme}")


@app.command("gate")
def gate_cmd(summary: Path,
             baseline: Annotated[Path | None, typer.Option("--baseline")] = None) -> None:
    """Exit 1 if the summary fails the gate (must-pass, not evaluated, regression)."""
    current = json.loads(summary.read_text(encoding="utf-8"))
    base = json.loads(baseline.read_text(encoding="utf-8")) if baseline and baseline.exists() else None
    ok, messages = report.gate(current, base)
    for m in messages:
        typer.echo(m)
    typer.echo("gate: PASS" if ok else "gate: FAIL")
    raise typer.Exit(0 if ok else 1)


@app.command("adk")
def adk_cmd(suite: Annotated[str, typer.Option("--suite")] = "regression",
            judges: Annotated[bool, typer.Option("--judges/--no-judges")] = False) -> None:
    """ADK metrics on evals/generated/<suite>.evalset.json (judge metrics: nightly only)."""
    result = adk_eval.run_adk(Path("evals/generated") / f"{suite}.evalset.json",
                              judge_metrics=["safety_v1", "hallucinations_v1"] if judges else [])
    for name in (k for k, v in result.items() if isinstance(v, dict)):
        r = result[name]
        mean = f"{r['mean']:.2f}" if r["mean"] is not None else "n/a"
        typer.echo(f"{name}: {mean} over {r['n']} cases")


def _model_factory():
    """None: each run uses the configured model (Vertex on the laptop). Tests swap in fakes."""
    return None


@app.command("transcripts")
def transcripts_cmd(batch: Path,
                    topology: Annotated[str, typer.Option("--topology")] = "single",
                    real: Annotated[bool, typer.Option("--real")] = False,
                    pace: Annotated[float, typer.Option("--pace")] = 0,
                    out: Annotated[Path, typer.Option("--out")] = Path("data/evals/transcripts.jsonl"),
                    workdir: Annotated[Path | None, typer.Option("--workdir")] = None) -> None:
    """Run a question batch through the agent (synthetic fixture, or --real) for labelling."""
    items = yaml.safe_load(batch.read_text(encoding="utf-8"))["questions"]
    rows = runner.run(items, topology=topology, model_factory=_model_factory(), real=real,
                      out=out, workdir=workdir, pace_s=pace)
    bad = [r for r in rows if r.status != "ok"]
    typer.echo(f"{len(rows)} transcripts -> {out} ({len(bad)} not evaluated)")


@app.command("compare")
def compare_cmd(old: Path, new: Path,
                cache: Annotated[Path, typer.Option("--cache")] = Path("data/evals/pairwise-cache.jsonl"),
                out: Annotated[Path | None, typer.Option("--out")] = None) -> None:
    """Blind pairwise judge: new answers vs the owner-labelled old ones (aggregates only)."""
    from . import judges

    labels = review.current_labels(old)
    result = report.compare_runs(runner.load(old), runner.load(new), labels,
                                 lambda o, n: judges.pairwise(o, n, cache=cache))
    text = json.dumps(result, indent=1)
    typer.echo(text)
    if out:
        out.write_text(text + "\n", encoding="utf-8")
