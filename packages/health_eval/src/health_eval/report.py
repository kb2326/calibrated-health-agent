"""Eval results: run and grade a suite, summarise, render, and decide the CI gate.

Rates use each case's first trial (so a flake still shows in the numbers); pass^k uses every
case that ran at least twice. The gate fails on:

1. a must-pass case with no passing trial (a failure that passes its one retry is a flake:
   reported, not gating);
2. any case that was not evaluated (quota, model error, truth query error), with the reason —
   never a silent pass;
3. a suite rate drop against the `main` baseline beyond the noise band
   `max(0.05, 2 x sd)` (sd from nightly pass^3 runs, when known). With no baseline yet the
   regression check is skipped and the gate says so.
"""
from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from health_agents import sqlguard

from . import graders, runner, stats
from .cases import Case

RESULTS = Path("docs/evals/results")
START, END = "<!-- scorecard:start -->", "<!-- scorecard:end -->"
MIN_BAND = 0.05

Outcomes = dict[tuple[str, int], list[graders.Verdict]]


def run_suite(cases: Sequence[Case], *, trials: int = 1, retry_must_pass: bool = True,
              model_factory: Callable[[], Any] | None = None, workdir: Path | None = None,
              pace_s: float = 0, out: Path) -> tuple[list[runner.Transcript], Outcomes]:
    """Run, grade inside the fixture (receipts re-run there), retry failed must-pass cases once."""
    by_id = {c.id: c for c in cases}
    commit = runner._commit()
    verdicts: Outcomes = {}
    with runner.eval_fixture(workdir) as (path, digest):
        conn, _ = sqlguard.guarded_connect(path)
        try:
            def go(chosen: Sequence[Case], first_trial: int, n: int) -> list[runner.Transcript]:
                ts = runner.collect(chosen, trials=n, model_factory=model_factory,
                                    commit=commit, fixture_hash=digest, pace_s=pace_s)
                for t in ts:
                    t.trial += first_trial
                    verdicts[(t.case_id, t.trial)] = graders.grade(t, by_id[t.case_id], conn)
                return ts

            transcripts = go(cases, 0, trials)
            if retry_must_pass:
                failed = [c for c in cases if c.expect.must_pass and not any(
                    graders.case_passed(verdicts[(c.id, k)]) for k in range(trials))]
                transcripts += go(failed, trials, 1)
        finally:
            conn.close()
    runner.write(transcripts, out)
    return transcripts, verdicts


def _rate(values: list[bool]) -> dict:
    k, n = sum(values), len(values)
    return {"k": k, "n": n, "rate": k / n if n else None, "ci": list(stats.wilson(k, n))}


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def summarise(transcripts: list[runner.Transcript], cases: Sequence[Case], verdicts: Outcomes,
              judge_status: dict, *, redteam: dict | None = None,
              ablation: dict | None = None) -> dict:
    by_id = {c.id: c for c in cases}
    trials: dict[str, dict[int, bool | None]] = defaultdict(dict)
    for (cid, trial), vs in verdicts.items():
        trials[cid][trial] = graders.case_passed(vs)
    reasons = {(t.case_id, t.trial): t.reason for t in transcripts if t.status != "ok"}
    not_evaluated = []
    for (cid, trial), vs in sorted(verdicts.items()):
        if graders.case_passed(vs) is None:
            reason = reasons.get((cid, trial)) or next(
                (v.detail for v in vs if v.passed is None and v.check != "cost_latency"), "unknown")
            not_evaluated.append({"case_id": cid, "trial": trial, "reason": reason})

    suites: dict[str, dict] = {}
    for suite in sorted({c.suite for c in cases}):
        members = [c for c in cases if c.suite == suite]
        first = [(c, trials[c.id].get(0)) for c in members]
        graded = [(c, r) for c, r in first if r is not None]
        repeated = [list(trials[c.id].values()) for c in members if len(trials[c.id]) >= 2]
        repeated = [r for r in repeated if None not in r]
        cats: dict[str, dict] = {}
        for cat in sorted({c.category for c in members}):
            cats[cat] = _rate([bool(r) for c, r in graded if c.category == cat])
        suites[suite] = {**_rate([bool(r) for _, r in graded]),
                         "not_evaluated": len(first) - len(graded),
                         "trials": max((len(trials[c.id]) for c in members), default=0),
                         "pass_hat_k": stats.pass_hat_k(repeated) if repeated else None,  # type: ignore[arg-type]
                         "categories": cats}

    def outcomes(cid: str) -> list[bool | None]:
        return list(trials[cid].values())

    must_pass_failed = sorted(cid for cid, c in by_id.items() if c.expect.must_pass
                              and False in outcomes(cid) and True not in outcomes(cid))
    flaky = sorted(cid for cid in trials if True in outcomes(cid) and False in outcomes(cid))
    ok = [t for t in transcripts if t.status == "ok"]
    seconds = [t.seconds for t in ok]
    return {
        "date": datetime.now(UTC).strftime("%Y-%m-%d"), "commit": _commit(),
        "transcripts": len(transcripts), "suites": suites,
        "must_pass_failed": must_pass_failed, "flaky": flaky, "not_evaluated": not_evaluated,
        "latency": {"p50": float(np.percentile(seconds, 50)) if seconds else None,
                    "p95": float(np.percentile(seconds, 95)) if seconds else None},
        "usd_per_question": sum(t.usd for t in ok) / len(ok) if ok else None,
        "judges": judge_status, "redteam": redteam, "ablation": ablation,
    }


def gate(current: dict, baseline: dict | None) -> tuple[bool, list[str]]:
    messages = []
    for cid in current.get("must_pass_failed", []):
        messages.append(f"FAIL must-pass case {cid} failed and its retry failed too")
    for ne in current.get("not_evaluated", []):
        messages.append(f"FAIL case {ne['case_id']} (trial {ne['trial']}) was not evaluated: "
                        f"{ne['reason']}")
    if baseline is None:
        messages.append("no baseline yet: regression check skipped")
    else:
        noise = baseline.get("noise_sd") or {}
        for suite, cur in current.get("suites", {}).items():
            base = baseline.get("suites", {}).get(suite)
            if not base or base.get("rate") is None or cur.get("rate") is None:
                continue
            band = max(MIN_BAND, 2 * float(noise.get(suite, 0)))
            drop = base["rate"] - cur["rate"]
            if drop > band + 1e-9:
                messages.append(f"FAIL {suite} regression: {base['rate']:.2f} -> {cur['rate']:.2f}"
                                f" (drop {drop:.2f} > band {band:.2f})")
    for cid in current.get("flaky", []):
        messages.append(f"note: {cid} is flaky (failed, then passed on retry)")
    return not any(m.startswith("FAIL") for m in messages), messages


def _fmt_rate(s: dict) -> str:
    if not s.get("n"):
        return "n = 0"
    lo, hi = s["ci"]
    return f"{s['k']}/{s['n']} = {s['rate']:.0%} (95% CI {lo:.0%}–{hi:.0%})"


def readme_block(summary: dict) -> str:
    lines = [f"Eval scorecard, {summary['date']} @ `{summary['commit']}` (synthetic fixture).", "",
             "| Suite | Pass rate | pass^k |", "|---|---|---|"]
    for suite, s in summary["suites"].items():
        phk = f"{s['pass_hat_k']:.0%}" if s.get("pass_hat_k") is not None else "–"
        lines.append(f"| {suite} | {_fmt_rate(s)} | {phk} |")
    if not summary["suites"]:
        lines.append("| (none) | n = 0 | – |")
    return "\n".join(lines)


def replace_readme_block(text: str, block: str) -> str:
    if START not in text or END not in text:
        raise ValueError("README has no scorecard markers")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{START}\n{block}\n{END}{tail}"


def render(summary: dict) -> str:
    out = [f"# Eval results {summary['date']} @ {summary['commit']}", "",
           "Synthetic fixture only. Rates use each case's first trial; intervals are Wilson 95%.",
           "", "## Suites", ""]
    if not summary["suites"]:
        out.append("No cases ran (n = 0).")
    for suite, s in summary["suites"].items():
        out.append(f"### {suite}: {_fmt_rate(s)}")
        if s.get("pass_hat_k") is not None:
            out.append(f"pass^{s['trials']}: {s['pass_hat_k']:.0%}")
        if s.get("not_evaluated"):
            out.append(f"Not evaluated: {s['not_evaluated']}")
        out += ["", "| Category | Pass rate |", "|---|---|"]
        out += [f"| {cat} | {_fmt_rate(c)} |" for cat, c in s["categories"].items()]
        out.append("")
    lat = summary["latency"]
    out += ["## Cost and latency", "",
            f"- p50 latency: {lat['p50']:.1f}s, p95: {lat['p95']:.1f}s" if lat["p50"] is not None
            else "- latency: n = 0",
            f"- mean cost per question: ${summary['usd_per_question']:.4f} (list price; CI runs on "
            "the free tier)" if summary["usd_per_question"] is not None else "- cost: n = 0", ""]
    out += ["## Gate inputs", "",
            f"- must-pass failures: {', '.join(summary['must_pass_failed']) or 'none'}",
            f"- flaky (passed on retry): {', '.join(summary['flaky']) or 'none'}",
            f"- not evaluated: {len(summary['not_evaluated'])}"]
    out += [f"  - {ne['case_id']} trial {ne['trial']}: {ne['reason']}"
            for ne in summary["not_evaluated"]]
    out.append("")
    if summary.get("judges"):
        out += ["## Judges", "", "| Judge | TPR | TNR | n | Gates |", "|---|---|---|---|---|"]
        for name, j in summary["judges"].items():
            tpr = f"{j['tpr']:.2f}" if j.get("tpr") is not None else "–"
            tnr = f"{j['tnr']:.2f}" if j.get("tnr") is not None else "–"
            out.append(f"| {name} | {tpr} | {tnr} | {j.get('n', 0)} | "
                       f"{'yes' if j.get('gates') else 'no (reported only)'} |")
        out.append("")
    if summary.get("redteam"):
        out += ["## Red team", "", "```json", json.dumps(summary["redteam"], indent=1), "```", ""]
    if summary.get("ablation"):
        out += ["## Ablation", "", "| Comparison | n | b | c | p (McNemar) | diff | MDD |",
                "|---|---|---|---|---|---|---|"]
        for name, c in summary["ablation"].get("comparisons", {}).items():
            mdd = f"{c['mdd']:.2f}" if c.get("mdd") is not None else "–"
            out.append(f"| {name} | {c['n']} | {c['b']} | {c['c']} | {c['p_mcnemar']:.3f} | "
                       f"{c['diff']:+.2f} | {mdd} |")
        out.append("")
    return "\n".join(out)


def write_results(summary: dict, out: Path = RESULTS) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{summary['date']}-{summary['commit']}.md"
    path.write_text(render(summary), encoding="utf-8")
    path.with_suffix(".json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return path
