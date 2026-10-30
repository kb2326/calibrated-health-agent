"""ADK's built-in evaluation metrics on the generated evalsets, next to our own graders.

The workflow runs on the synthetic fixture through ADK's `LocalEvalService` (inference, then
metric evaluation), so the scores are the ones `adk eval` would report. Our graph `Workflow`
is passed as the root node directly.

- `tool_trajectory_avg_score` (every run): ANY_ORDER, arguments ignored, scored only on cases
  that name exactly one expected tool (see `cases.to_evalset`). Our `tools_any` grader covers
  the cases that accept several tools.
- Judge metrics such as `safety_v1` and `hallucinations_v1` call a model per case, so they run
  nightly only (`judge_metrics=[...]`), never on a pull request.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import runner

APP = "calibrated_health_agent"
TRAJECTORY = "tool_trajectory_avg_score"


def _metric(name: str) -> Any:
    from google.adk.evaluation.eval_metrics import (
        EvalMetric,
        JudgeModelOptions,
        LlmAsAJudgeCriterion,
        ToolTrajectoryCriterion,
    )

    if name == TRAJECTORY:
        return EvalMetric(metric_name=name, criterion=ToolTrajectoryCriterion(
            threshold=1.0, match_type=ToolTrajectoryCriterion.MatchType.ANY_ORDER,
            ignore_args=True))
    if name == "hallucinations_v1":
        return EvalMetric(metric_name=name, criterion=LlmAsAJudgeCriterion(
            threshold=0.8, judge_model_options=JudgeModelOptions()))
    return EvalMetric(metric_name=name, threshold=0.8)


def _expects_tool(case: Any) -> bool:
    last = case.conversation[-1] if case.conversation else None
    return bool(last and last.intermediate_data and last.intermediate_data.tool_uses)


async def _run(eval_set: Any, root: Any, metrics: Sequence[str],
               judge_metrics: Sequence[str]) -> dict:
    from google.adk.evaluation.base_eval_service import (
        EvaluateConfig,
        EvaluateRequest,
        InferenceConfig,
        InferenceRequest,
    )
    from google.adk.evaluation.in_memory_eval_sets_manager import InMemoryEvalSetsManager
    from google.adk.evaluation.local_eval_service import LocalEvalService

    manager = InMemoryEvalSetsManager()
    manager.create_eval_set(app_name=APP, eval_set_id=eval_set.eval_set_id)
    for case in eval_set.eval_cases:
        manager.add_eval_case(app_name=APP, eval_set_id=eval_set.eval_set_id, eval_case=case)
    service = LocalEvalService(root_agent=root, eval_sets_manager=manager)
    inferences = []
    request = InferenceRequest(app_name=APP, eval_set_id=eval_set.eval_set_id,
                               inference_config=InferenceConfig())
    async for result in service.perform_inference(inference_request=request):
        inferences.append(result)

    with_tool = {c.eval_id for c in eval_set.eval_cases if _expects_tool(c)}
    out: dict[str, Any] = {}
    for name in [*metrics, *judge_metrics]:
        chosen = [r for r in inferences if name != TRAJECTORY or r.eval_case_id in with_tool]
        per_case: dict[str, float | None] = {}
        if chosen:
            evaluate = EvaluateRequest(inference_results=chosen,
                                       evaluate_config=EvaluateConfig(eval_metrics=[_metric(name)]))
            async for res in service.evaluate(evaluate_request=evaluate):
                scores = [m.score for m in res.overall_eval_metric_results
                          if m.metric_name == name]
                per_case[res.eval_id] = scores[0] if scores else None
        scored = [s for s in per_case.values() if s is not None]
        out[name] = {"mean": sum(scored) / len(scored) if scored else None, "n": len(scored),
                     "per_case": per_case}
    return out


def run_adk(evalset: Path, *, metrics: Sequence[str] = (TRAJECTORY,),
            judge_metrics: Sequence[str] = (), model: Any = None,
            workdir: Path | None = None) -> dict:
    """Run ADK metrics on one generated evalset against the fixture; `{metric: {mean, n,
    per_case}}`. `model` overrides the configured one (tests pass a fake)."""
    from google.adk.evaluation.eval_set import EvalSet
    from health_agents.workflow import build_workflow

    eval_set = EvalSet.model_validate(json.loads(Path(evalset).read_text(encoding="utf-8")))
    with runner.eval_fixture(workdir):
        root = build_workflow("single", model=model)
        result = asyncio.run(_run(eval_set, root, metrics, judge_metrics))
    return {"evalset": eval_set.eval_set_id, "cases": len(eval_set.eval_cases),
            "judge_metrics": list(judge_metrics), **result}
