"""ADK's own evaluation metrics run on the generated evalsets, offline with a fake model."""
from __future__ import annotations

import pytest
from agent_fakes import FakeLlm, call, text
from health_eval import adk_eval
from health_eval.cases import Case, Expect, to_evalset

CASES = [Case("c1", "regression", "n", "How many journal entries?", Expect(tools_any=["run_sql"])),
         Case("c2", "regression", "n", "Count my journal entries.", Expect(tools_any=["run_sql"])),
         Case("c3", "regression", "n", "Steps trend?",
              Expect(tools_any=["run_sql", "run_python"]))]


def test_multi_option_tools_are_not_expected_tool_uses():
    data = to_evalset(CASES, "s")
    uses = {c["eval_id"]: c["conversation"][-1]["intermediate_data"].get("tool_uses", [])
            for c in data["eval_cases"]}
    assert [u["name"] for u in uses["c1"]] == ["run_sql"] and uses["c3"] == []


def test_adk_trajectory_metric_runs_on_generated_evalset(tmp_path):
    # ADK runs cases concurrently, so the fake answers from the request, not from call order:
    # c1 ("How many") calls run_sql once, everything else answers in text
    def step(request):
        parts = [p for c in request.contents for p in (c.parts or [])]
        asked = " ".join(p.text or "" for p in parts)
        if "How many journal" in asked and not any(p.function_response for p in parts):
            return call("run_sql", query="SELECT COUNT(*) AS n FROM journal_submissions")
        return text("You have 41 entries.")

    fake = FakeLlm([step])
    path = tmp_path / "s.evalset.json"
    import json
    path.write_text(json.dumps(to_evalset(CASES, "s")), encoding="utf-8")
    result = adk_eval.run_adk(path, model=fake, workdir=tmp_path / "w")
    traj = result["tool_trajectory_avg_score"]
    assert traj["per_case"] == {"c1": 1.0, "c2": 0.0}  # c3 has no single expected tool
    assert traj["mean"] == pytest.approx(0.5) and traj["n"] == 2
    assert result["cases"] == 3 and result["judge_metrics"] == []
