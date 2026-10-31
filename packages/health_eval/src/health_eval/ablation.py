"""Ablation: does each part of the agent earn its place?

Four arms run the same cases on the same fixture: `no_tools` (the model alone), `no_code`
(tools but no `run_python`), `full` (single agent, every tool) and `multi` (the specialist
topology). Outcomes are paired by case, so comparisons use the exact McNemar test on the
discordant cases and a paired bootstrap for the size of the difference, each reported with the
minimum detectable difference for that many cases. With several trials a case counts as passed
in an arm only if every trial passed (pass^k), and as not evaluated if any trial was.
"""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from health_agents import sqlguard

from . import graders, runner, stats
from .cases import Case

ARMS: dict[str, tuple[str, runner.Variant]] = {
    "no_tools": ("single", "no_tools"), "no_code": ("single", "no_code"),
    "full": ("single", "full"), "multi": ("multi", "full"),
}
COMPARISONS = {"full_vs_no_code": ("full", "no_code"), "full_vs_no_tools": ("full", "no_tools"),
               "single_vs_multi": ("full", "multi")}


# Arms are compared on answer accuracy only: tool-use and unverified checks would fail the
# no-tools arm by construction and make every comparison with it meaningless.
ARM_CHECKS = ("numbers", "status")


def _outcomes(transcripts: list[runner.Transcript], cases: dict[str, Case],
              conn: Any) -> dict[str, bool | None]:
    per_case: dict[str, list[bool | None]] = defaultdict(list)
    for t in transcripts:
        verdicts = [v for v in graders.grade(t, cases[t.case_id], conn) if v.check in ARM_CHECKS]
        per_case[t.case_id].append(graders.case_passed(verdicts))
    return {cid: None if None in results else all(results) for cid, results in per_case.items()}


def _arm_summary(outcomes: dict[str, bool | None]) -> dict:
    graded = [v for v in outcomes.values() if v is not None]
    k, n = sum(graded), len(graded)
    return {"k": k, "n": n, "rate": k / n if n else None, "ci": list(stats.wilson(k, n)),
            "not_evaluated": len(outcomes) - n}


def _compare(a: dict[str, bool | None], b: dict[str, bool | None]) -> dict:
    ids = [cid for cid in a if a[cid] is not None and b.get(cid) is not None]
    xa = [bool(a[cid]) for cid in ids]
    xb = [bool(b[cid]) for cid in ids]
    only_a = sum(x and not y for x, y in zip(xa, xb, strict=True))
    only_b = sum(y and not x for x, y in zip(xa, xb, strict=True))
    diff, lo, hi = stats.paired_bootstrap_diff(xa, xb)
    return {"n": len(ids), "b": only_a, "c": only_b, "p_mcnemar": stats.mcnemar_exact(only_a, only_b),
            "diff": diff, "ci": [lo, hi],
            "mdd": stats.min_detectable_diff(len(ids)) if ids else None}


def run_ablation(cases: Sequence[Case], *, trials: int = 1, out_dir: Path,
                 model_factory: Callable[[str], Any] | None = None,
                 workdir: Path | None = None) -> dict:
    """Run every arm, write `<arm>.jsonl` and `ablation.json` to `out_dir`, return the summary.

    `model_factory(arm)` gives each run its model (tests pass fakes); None uses the configured
    model, so a live run costs (4 arms x cases x trials) agent turns.
    """
    out_dir = Path(out_dir)
    by_id = {c.id: c for c in cases}
    commit = runner._commit()
    outcomes: dict[str, dict[str, bool | None]] = {}
    with runner.eval_fixture(workdir) as (path, digest):
        conn, _ = sqlguard.guarded_connect(path)
        try:
            for arm, (topology, variant) in ARMS.items():
                factory = (lambda arm=arm: model_factory(arm)) if model_factory else None
                transcripts = runner.collect(cases, topology=topology, trials=trials,
                                             variant=variant, model_factory=factory,
                                             commit=commit, fixture_hash=digest)
                runner.write(transcripts, out_dir / f"{arm}.jsonl")
                outcomes[arm] = _outcomes(transcripts, by_id, conn)
        finally:
            conn.close()
    result = {"cases": len(cases), "trials": trials, "commit": commit, "fixture_hash": digest,
              "arms": {arm: _arm_summary(o) for arm, o in outcomes.items()},
              "comparisons": {name: _compare(outcomes[a], outcomes[b])
                              for name, (a, b) in COMPARISONS.items()}}
    (out_dir / "ablation.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return result
