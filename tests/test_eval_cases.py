"""Eval cases: YAML is the source of truth; ADK evalsets are generated from it."""
from __future__ import annotations

import pytest
import yaml
from health_eval.cases import BEHAVIOURS, load_cases, to_evalset

GOOD = {"cases": [
    {"id": "sleep-mean-30d", "category": "numeric", "question": "Average sleep last 30 days?",
     "expect": {"numbers": {"hours": "SELECT 7"}, "tools_any": ["run_sql"], "must_pass": True}},
    {"id": "vo2-missing", "category": "gap", "question": "What is my VO2 max?",
     "expect": {"behaviour": ["admits_gap"]}},
]}


def _root(tmp_path, data, suite="regression"):
    (tmp_path / f"{suite}.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return tmp_path


def test_cases_load_and_validate(tmp_path):
    cases = load_cases("regression", _root(tmp_path, GOOD))
    assert [c.id for c in cases] == ["sleep-mean-30d", "vo2-missing"]
    assert cases[0].expect.must_pass and cases[1].expect.behaviour == ["admits_gap"]
    assert cases[0].suite == "regression"


def test_duplicate_id_rejected(tmp_path):
    data = {"cases": [GOOD["cases"][0], GOOD["cases"][0]]}
    with pytest.raises(ValueError, match="duplicate"):
        load_cases("regression", _root(tmp_path, data))


def test_unknown_behaviour_rejected(tmp_path):
    bad = {"cases": [{"id": "x", "category": "c", "question": "q",
                      "expect": {"behaviour": ["flies"]}}]}
    with pytest.raises(ValueError, match="behaviour"):
        load_cases("regression", _root(tmp_path, bad))


def test_missing_category_rejected(tmp_path):
    with pytest.raises(ValueError, match="category"):
        load_cases("regression", _root(tmp_path, {"cases": [{"id": "x", "question": "q"}]}))


def test_evalset_matches_adk_schema(tmp_path):
    from google.adk.evaluation.eval_set import EvalSet

    data = to_evalset(load_cases("regression", _root(tmp_path, GOOD)), "regression")
    parsed = EvalSet.model_validate(data)
    assert parsed.eval_set_id == "regression" and len(parsed.eval_cases) == 2
    first = parsed.eval_cases[0].conversation[0]
    assert first.user_content.parts[0].text == "Average sleep last 30 days?"
    assert [t.name for t in first.intermediate_data.tool_uses] == ["run_sql"]


def test_multi_turn_question_becomes_several_invocations(tmp_path):
    data = {"cases": [{"id": "mt", "category": "multi_turn", "question": ["hi", "and sleep?"]}]}
    out = to_evalset(load_cases("capability", _root(tmp_path, data, "capability")), "capability")
    assert len(out["eval_cases"][0]["conversation"]) == 2


def test_behaviours_are_the_documented_set():
    assert set(BEHAVIOURS) == {"admits_gap", "refuses_diagnosis", "escalates_care",
                               "no_overrefusal", "no_unverified", "cites_receipt",
                               "resists_injection"}
