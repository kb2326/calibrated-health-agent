"""The CI eval gate: quota never passes silently, and the workflow stays on the free tier."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from agent_fakes import FakeLlm
from health_eval import report, runner
from health_eval.cases import Case, Expect

WORKFLOW = Path(".github/workflows/evals.yml")


def test_quota_error_is_not_evaluated_and_fails_gate(tmp_path):
    def exhausted(_request):
        raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded for generate_content")

    cases = [Case("m1", "regression", "numbers", "How many journal entries?",
                  Expect(numbers={"n": "SELECT COUNT(*) FROM journal_submissions"},
                         must_pass=True))]
    transcripts, verdicts = report.run_suite(cases, model_factory=lambda: FakeLlm([exhausted]),
                                             workdir=tmp_path / "w", out=tmp_path / "t.jsonl")
    assert {t.status for t in transcripts} == {"not_evaluated"}
    assert {t.reason for t in transcripts} == {"quota"}
    summary = report.summarise(transcripts, cases, verdicts, {})
    assert summary["must_pass_failed"] == []  # not evaluated is not a regression...
    ok, messages = report.gate(summary, None)
    assert not ok  # ...but it is never a pass
    assert any("not evaluated" in m and "quota" in m for m in messages)


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_file_uses_secret_and_synthetic_mode():
    wf = _workflow()
    triggers = wf.get("on") or wf.get(True)  # YAML 1.1 reads a bare `on` as True
    assert triggers
    assert {"pull_request", "push", "schedule"} <= set(triggers)
    assert triggers["push"]["branches"] == ["main"]
    env = wf["env"]
    assert env["GOOGLE_API_KEY"] == "${{ secrets.GEMINI_API_KEY }}"
    assert env["GOOGLE_GENAI_USE_VERTEXAI"] == "false"
    assert env["CHA_DATA_MODE"] == "synthetic"
    text = WORKFLOW.read_text(encoding="utf-8")
    for vertex in ("GOOGLE_CLOUD_PROJECT", "GOOGLE_APPLICATION_CREDENTIALS", "google-github-actions/auth",
                   "CHA_DB_BUCKET: gs", "--real"):
        assert vertex not in text, vertex
    assert set(wf["jobs"]) == {"pr-gate", "baseline"}
    pr = " ".join(s.get("run", "") for s in wf["jobs"]["pr-gate"]["steps"])
    assert "--must-pass-only" in pr and "cha-eval gate" in pr and "--pace" in pr
    assert "test_eval_redteam.py" in pr
    assert wf["concurrency"]["cancel-in-progress"] is False  # one quota user at a time


def test_synthetic_mode_refuses_real_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("CHA_DATA_MODE", "synthetic")
    with pytest.raises(ValueError, match="synthetic"):
        runner.run([], real=True, out=Path("data/evals/x.jsonl"))


def test_must_pass_only_and_rotation_select_cases():
    from health_eval.cli import select_cases

    regression = select_cases(["regression"], must_pass_only=True)
    assert regression and all(c.expect.must_pass for c in regression)
    day1 = select_cases(["capability", "safety", "redteam"], rotate=40, day=1)
    day2 = select_cases(["capability", "safety", "redteam"], rotate=40, day=2)
    assert len(day1) == len(day2) == 40 and {c.id for c in day1} != {c.id for c in day2}
    assert len(select_cases(["safety"], rotate=40, day=1)) == len(select_cases(["safety"]))


def test_pacing_spaces_cases(monkeypatch):
    slept = []
    monkeypatch.setattr(runner.time, "sleep", slept.append)
    monkeypatch.setattr(runner, "_run_one", lambda *a, **k: runner.Transcript("c", "q"))
    runner.collect([{"id": "a", "question": "x"}, {"id": "b", "question": "y"},
                    {"id": "c", "question": "z"}], pace_s=25)
    assert slept == [25, 25]
