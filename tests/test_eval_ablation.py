"""Ablation: every arm runs the same cases, and comparisons pair outcomes by case."""
from __future__ import annotations

import json

import pytest
from agent_fakes import FakeLlm, call, text
from health_eval import ablation, stats
from health_eval.cases import Case, Expect

COUNT = "SELECT COUNT(*) FROM journal_submissions"  # 41 on the eval fixture
CASES = [Case(f"a{i}", "ablation", "numbers", "How many journal entries do I have?",
              Expect(numbers={"n": COUNT})) for i in range(3)]


def _arm(arm: str) -> FakeLlm:
    sql = call("run_sql", query="SELECT COUNT(*) AS n FROM journal_submissions")
    if arm == "no_tools":
        return FakeLlm([text("You have about 12 entries.")])
    return FakeLlm([sql, text("You have 41 journal entries.")])


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    out = tmp_path_factory.mktemp("abl")
    return ablation.run_ablation(CASES, out_dir=out, model_factory=_arm,
                                 workdir=out / "work"), out


def test_ablation_pairs_by_case(result):
    res, out = result
    arms = res["arms"]
    assert arms["full"]["k"] == 3 and arms["full"]["n"] == 3
    assert arms["no_code"]["k"] == 3 and arms["multi"]["k"] == 3
    assert arms["no_tools"]["k"] == 0 and arms["no_tools"]["n"] == 3
    assert arms["full"]["ci"] == pytest.approx(stats.wilson(3, 3))
    tools = res["comparisons"]["full_vs_no_tools"]
    assert (tools["b"], tools["c"], tools["n"]) == (3, 0, 3)
    assert tools["p_mcnemar"] == pytest.approx(stats.mcnemar_exact(3, 0))
    assert tools["diff"] == pytest.approx(1.0)
    multi = res["comparisons"]["single_vs_multi"]
    assert (multi["b"], multi["c"], multi["p_mcnemar"]) == (0, 0, 1.0)
    for arm in ablation.ARMS:
        rows = (out / f"{arm}.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(rows) == 3
    assert {json.loads(r)["topology"] for r in
            (out / "multi.jsonl").read_text(encoding="utf-8").splitlines()} == {"multi"}


def test_ablation_reports_mdd(result):
    res, out = result
    for name in ("full_vs_no_code", "full_vs_no_tools", "single_vs_multi"):
        assert res["comparisons"][name]["mdd"] == pytest.approx(stats.min_detectable_diff(3))
    assert json.loads((out / "ablation.json").read_text(encoding="utf-8")) == res


def test_arms_are_compared_on_numbers_only(monkeypatch):
    # final review I8: the no-tools arm must not fail by construction on tools_any
    from health_eval import graders
    from health_eval.runner import Transcript

    def fake_grade(t, case, conn, rerun=None):
        return [graders.Verdict("numbers", True, ""), graders.Verdict("tools_any", False, ""),
                graders.Verdict("no_unverified", False, "")]

    monkeypatch.setattr(graders, "grade", fake_grade)
    case = Case("a", "ablation", "numbers", "q",
                Expect(numbers={"n": COUNT}, tools_any=["run_sql"]))
    out = ablation._outcomes([Transcript(case_id="a", question="q")], {"a": case}, None)
    assert out == {"a": True}
