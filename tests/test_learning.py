"""Tests for the learning loop and the agent's tool surface.

The claim this loop makes is falsifiable and therefore testable: a signal
that never predicts correctly must end up demoted, and one that predicts
reliably must end up promoted. If those two don't hold, the loop is
decoration.
"""
from __future__ import annotations

import importlib
from datetime import date, timedelta

import pytest
from health_data import db


@pytest.fixture
def substrate(tmp_path, monkeypatch):
    """A throwaway database with learn.py bound to it."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    learn = importlib.import_module("health_data.legacy.learn")
    importlib.reload(learn)
    monkeypatch.setattr(learn.db, "DB_PATH", tmp_path / "t.db")
    return learn


def _predict(conn, signal, signal_date, target, target_date, direction):
    conn.execute(
        """INSERT INTO predictions (made_on, signal, signal_date, signal_z,
             target, target_date, lag_days, expected_direction)
           VALUES (?,?,?,?,?,?,1,?)""",
        (signal_date, signal, signal_date, 2.0, target, target_date, direction),
    )


def _journal(conn, day, **fields):
    conn.execute(
        "INSERT OR REPLACE INTO journal (date, mood, energy, soreness, logged_at) "
        "VALUES (?,?,?,?,?)",
        (day, fields.get("mood"), fields.get("energy"),
         fields.get("soreness"), db.now_iso()),
    )


def _seed(conn, signal, correct: bool, n=8, target="energy"):
    """Emit n predictions and journal entries where the signal is right/wrong.

    The journal alternates high and low around a mean of 5 so the field has
    real spread — a flat journal is explicitly not scoreable.
    """
    base = date(2026, 6, 1)
    for i in range(n):
        sd = (base + timedelta(days=i * 2)).isoformat()
        td = (base + timedelta(days=i * 2 + 1)).isoformat()
        # alternate the actual outcome so the journal varies
        actual_high = i % 2 == 0
        direction = "high" if (actual_high == correct) else "low"
        _predict(conn, signal, sd, target, td, direction)
        _journal(conn, td, **{target: 9 if actual_high else 2})
    # history so _journal_baseline has something to work with
    for i in range(6):
        _journal(conn, (base - timedelta(days=i + 1)).isoformat(),
                 **{target: 5 + (i % 3) - 1})


class TestLearningLoop:
    def test_a_reliable_signal_is_promoted(self, substrate):
        learn = substrate
        with db.connect() as conn:
            _seed(conn, "sleep", correct=True)
            conn.commit()
        out = learn.run(today="2026-07-01")
        assert out["scored"] >= 5
        sig = [s for s in out["signals"] if s["signal"] == "sleep"][0]
        assert sig["hit_rate"] == 1.0
        assert sig["weight"] > 1.0, "a signal that always predicts must gain weight"

    def test_an_unreliable_signal_is_demoted(self, substrate):
        learn = substrate
        with db.connect() as conn:
            _seed(conn, "oxygen-saturation", correct=False)
            conn.commit()
        out = learn.run(today="2026-07-01")
        sig = [s for s in out["signals"] if s["signal"] == "oxygen-saturation"][0]
        assert sig["hit_rate"] == 0.0
        assert sig["weight"] < 1.0, "a signal that never predicts must lose weight"

    def test_weight_changes_the_detection_threshold(self, substrate):
        """The whole point: a learned weight must alter what gets flagged."""
        analyze = importlib.import_module("health_data.legacy.analyze")
        importlib.reload(analyze)

        base = analyze.A["watch_z"]
        assert analyze._severity(base + 0.01, weight=1.0) == "watch"
        # A demoted signal must need a bigger deviation to reach the same call
        assert analyze._severity(base + 0.01, weight=0.6) == "normal"
        # A promoted one reaches it sooner
        assert analyze._severity(base - 0.3, weight=1.4) == "watch"

    def test_weight_is_bounded_in_both_directions(self, substrate):
        learn = substrate
        assert learn.WEIGHT_FLOOR > 0, "a zero weight would divide by zero downstream"
        with db.connect() as conn:
            _seed(conn, "sleep", correct=True, n=40)
            conn.commit()
        out = learn.run(today="2026-07-01")
        sig = [s for s in out["signals"] if s["signal"] == "sleep"][0]
        assert sig["weight"] <= learn.WEIGHT_CEILING

    def test_thin_evidence_does_not_move_the_weight(self, substrate):
        """Two lucky guesses are not evidence; the weight must stay neutral."""
        learn = substrate
        with db.connect() as conn:
            _seed(conn, "exercise", correct=True, n=2)
            conn.commit()
        out = learn.run(today="2026-07-01")
        sig = [s for s in out["signals"] if s["signal"] == "exercise"]
        if sig:
            assert sig[0]["weight"] == 1.0

    def test_unscored_predictions_stay_pending(self, substrate):
        """A day with no journal entry is unanswered, never a miss."""
        learn = substrate
        with db.connect() as conn:
            _predict(conn, "sleep", "2026-06-01", "energy", "2026-06-02", "high")
            conn.commit()
        out = learn.run(today="2026-07-01")
        assert out["scored"] == 0
        with db.connect() as conn:
            hit = conn.execute("SELECT hit FROM predictions").fetchone()[0]
        assert hit is None, "an unanswered prediction must not be scored as wrong"

    def test_flat_journal_is_not_scoreable(self, substrate):
        """Predicting a constant is not a skill."""
        learn = substrate
        base = date(2026, 6, 1)
        with db.connect() as conn:
            for i in range(10):
                _journal(conn, (base + timedelta(days=i)).isoformat(), energy=5)
            _predict(conn, "sleep", (base + timedelta(days=8)).isoformat(),
                     "energy", (base + timedelta(days=9)).isoformat(), "high")
            conn.commit()
        out = learn.run(today="2026-07-01")
        assert out["scored"] == 0


class TestAgentTools:
    """The agent's capability surface — read-only, grounded, honest about n."""

    @pytest.fixture(autouse=True)
    def empty_db(self, tmp_path, monkeypatch):
        """Bind tools to a throwaway schema-only DB so no real data/ is needed."""
        monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
        db.init_db()

    def test_sql_tool_refuses_every_mutation(self):
        from health_agents import tools
        for q in ("DELETE FROM journal", "UPDATE journal SET mood=1",
                  "DROP TABLE journal", "INSERT INTO journal VALUES (1)",
                  "PRAGMA journal_mode=DELETE", "SELECT 1; DROP TABLE journal"):
            assert "error" in tools.run_sql(q), f"must refuse: {q}"

    def test_sql_tool_allows_reads(self):
        from health_agents import tools
        r = tools.run_sql("SELECT COUNT(*) AS c FROM daily_metrics")
        assert "error" not in r and r["n"] == 1

    def test_sql_tool_allows_a_cte(self):
        from health_agents import tools
        r = tools.run_sql("WITH t AS (SELECT 1 AS x) SELECT x FROM t")
        assert "error" not in r

    def test_connection_itself_is_read_only(self):
        """Belt and braces: even past the guard, SQLite refuses the write."""
        import sqlite3

        from health_agents import tools
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            tools._ro_connect().execute("DELETE FROM journal")

    def test_every_tool_reports_a_sample_count(self):
        """Grounding rule: a claim without n is not checkable."""
        from health_agents import tools
        for result in (tools.get_anomalies(30), tools.get_journal(30),
                       tools.get_correlations(0.3), tools.get_metric_series("steps", 30)):
            assert "n" in result

    def test_definitional_pairs_are_flagged(self):
        """distance vs steps is the same walking measured twice."""
        from health_agents import tools
        corr = tools.get_correlations(0.3)["correlations"]
        pairs = {(c["metric_a"], c["metric_b"]): c["definitional"] for c in corr}
        if ("distance", "steps") in pairs:
            assert pairs[("distance", "steps")] is True
