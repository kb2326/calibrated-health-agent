"""The exit-check smoke set: a deterministic synthetic database and a receipts check."""
from __future__ import annotations

import sqlite3

from agent_fakes import FakeLlm, call, text
from health_agents import smoke


def _digest(path):
    conn = sqlite3.connect(path)
    try:
        return (conn.execute("SELECT date, data_type, agg_value, source FROM daily_metrics "
                             "ORDER BY date, data_type").fetchall(),
                conn.execute("SELECT date, mood, energy, soreness, note, tags FROM "
                             "journal_submissions ORDER BY date").fetchall())
    finally:
        conn.close()


def test_smoke_fixture_is_deterministic(tmp_path):
    a = smoke.build_fixture(tmp_path / "a.db")
    b = smoke.build_fixture(tmp_path / "b.db")
    assert _digest(a) == _digest(b)
    metrics, journal = _digest(a)
    assert len({m[0] for m in metrics}) == smoke.DAYS
    assert len(journal) == smoke.JOURNAL_DAYS
    assert any(smoke.POISON in (j[4] or "") for j in journal)


def test_smoke_questions_file_has_ten_questions():
    assert len(smoke.load_questions()) == 10


def test_smoke_runner_with_fake_llm(tmp_path):
    llm = FakeLlm([call("run_sql", query="SELECT COUNT(*) AS n FROM journal_outcome"),
                   lambda req: text(f"You have {smoke.JOURNAL_DAYS} journal entries.")])
    report = smoke.run_smoke(["How many journal entries do I have?"], model=llm,
                             workdir=tmp_path)
    assert report["passed"] == 1 and report["total"] == 1
    assert report["results"][0]["receipts_rerun"] is True


def test_smoke_fails_an_answer_with_an_unbacked_number(tmp_path):
    llm = FakeLlm([text("You have 99 entries.")])
    report = smoke.run_smoke(["How many journal entries do I have?"], model=llm, workdir=tmp_path)
    assert report["passed"] == 0
    assert "unverified" in report["results"][0]["reason"]
