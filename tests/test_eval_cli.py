"""cha-eval transcripts: a question batch through the agent, for labelling."""
from __future__ import annotations

import json

import yaml
from agent_fakes import FakeLlm, text
from health_eval import cli
from typer.testing import CliRunner


def test_transcripts_runs_a_question_batch(tmp_path, monkeypatch):
    batch = tmp_path / "q.yaml"
    batch.write_text(yaml.safe_dump({"questions": [
        {"id": "q-001", "question": "How did I sleep?", "tags": {"intent": "lookup"}},
        {"id": "q-002", "question": "Steps this week?", "tags": {"intent": "lookup"}}]}),
        encoding="utf-8")
    monkeypatch.setattr(cli, "_model_factory", lambda: lambda: FakeLlm([text("Fine.")]))
    out = tmp_path / "t.jsonl"
    result = CliRunner().invoke(cli.app, ["transcripts", str(batch), "--topology", "multi",
                                          "--out", str(out), "--workdir", str(tmp_path / "w")])
    assert result.exit_code == 0, result.output
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["case_id"] for r in rows] == ["q-001", "q-002"]
    assert {r["topology"] for r in rows} == {"multi"} and rows[0]["tags"]["intent"] == "lookup"
