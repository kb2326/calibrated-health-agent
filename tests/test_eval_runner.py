"""The transcript runner: every run of a case leaves a JSONL record graders can read."""
from __future__ import annotations

import json

import pytest
from agent_fakes import FakeLlm, call, text
from health_eval import runner
from health_eval.cases import Case, Expect

CASES = [Case("c1", "regression", "numeric", "How many journal entries?",
              Expect(tools_any=["run_sql"])),
         Case("c2", "regression", "gap", "What is my VO2 max?")]


def _llm():
    return FakeLlm([call("run_sql", query="SELECT COUNT(*) AS n FROM journal_outcome"),
                    text("You have 41 entries.")])


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_runner_writes_one_line_per_trial(tmp_path):
    out = tmp_path / "t.jsonl"
    runner.run(CASES, topology="single", trials=2, model_factory=_llm, out=out, workdir=tmp_path / "w")
    rows = _lines(out)
    assert len(rows) == 4 and {r["trial"] for r in rows} == {0, 1}
    assert {r["case_id"] for r in rows} == {"c1", "c2"}


def test_transcript_has_tool_calls_and_receipts(tmp_path):
    out = tmp_path / "t.jsonl"
    runner.run(CASES[:1], topology="single", model_factory=_llm, out=out, workdir=tmp_path / "w")
    row = _lines(out)[0]
    assert row["status"] == "ok" and row["tool_calls"][0]["name"] == "run_sql"
    assert row["tool_calls"][0]["response"]["rows"] == [{"n": 41}]
    assert row["receipts"] and row["receipts"][0].startswith("r-")
    assert row["fixture_hash"] and row["commit"] and row["seconds"] >= 0


def test_no_code_variant_has_no_run_python(tmp_path):
    names = runner.variant_tools("no_code")
    assert names is not None and all(getattr(t, "name", getattr(t, "__name__", "")) != "run_python" for t in names)
    assert len(names) == 17
    assert runner.variant_tools("no_tools") == [] and runner.variant_tools("full") is None


def test_quota_error_becomes_not_evaluated(tmp_path):
    def boom(req):
        raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")
    out = tmp_path / "t.jsonl"
    runner.run(CASES[:1], topology="single", model_factory=lambda: FakeLlm([boom]), out=out,
               workdir=tmp_path / "w")
    row = _lines(out)[0]
    assert row["status"] == "not_evaluated" and row["reason"] == "quota"


def test_real_runs_refuse_committable_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="data/evals"):
        runner.run(CASES, topology="single", real=True, out=runner.Path("evals/x.jsonl"))


def test_fixture_rebuilds_into_a_reused_workdir(tmp_path):
    # final review I5: a second build into the same health.db crashed on UNIQUE
    from health_eval import fixture

    first = fixture.build(tmp_path / "health.db")
    again = fixture.build(tmp_path / "health.db")
    assert first == again and again.exists()


def test_run_paces_between_items(tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr(runner.time, "sleep", slept.append)
    runner.run(CASES, topology="single", model_factory=_llm, out=tmp_path / "t.jsonl",
               workdir=tmp_path / "w", pace_s=7)
    assert slept == [7]


@pytest.mark.parametrize("env", [
    {"GOOGLE_GENAI_USE_VERTEXAI": "false", "GOOGLE_API_KEY": "k"},
    {"GOOGLE_GENAI_USE_VERTEXAI": "true", "GOOGLE_API_KEY": "k"}])
def test_real_runs_require_vertex(tmp_path, monkeypatch, env):
    # final review I6: real health data must never go to the free-tier key
    monkeypatch.chdir(tmp_path)
    for var in ("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_API_KEY", "CHA_DATA_MODE"):
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ValueError, match="Vertex"):
        runner.run([], real=True, out=runner.Path("data/evals/r.jsonl"))
