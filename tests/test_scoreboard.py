"""The public scoreboard: aggregates and real n only, never a day's value."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import pytest
from health_ledger import chain, dist, scoreboard
from health_ledger.forecasters import gemini
from ledger_fixtures import make_db

G = gemini.FORECASTER_ID
START = date(2026, 9, 1)


def _scored_day(conn, day: date, outcomes: dict[str, int], bets: dict[str, dist.Dist]) -> None:
    d = day.isoformat()
    conn.execute("INSERT INTO snapshots VALUES (?, '{}', 'h', 't', '[]')", (d,))
    for name, p in bets.items():
        for target, y in outcomes.items():
            conn.execute("INSERT INTO forecasts (day, forecaster, target, probs_json, abstain_reason, "
                         "locked_at) VALUES (?, ?, ?, ?, NULL, 't')", (d, name, target, json.dumps(p)))
            conn.execute("INSERT INTO scores (day, forecaster, target, outcome, rps, log_score, "
                         "scored_at) VALUES (?, ?, ?, ?, ?, ?, 't')",
                         (d, name, target, y, dist.rps(p, y), dist.log_score(p, y)))
    chain.append(conn, d, "outcome", {"x": d})


@pytest.fixture
def conn(tmp_path):
    c = make_db(tmp_path / "t.db")
    chain.ensure_plan_hash(c, "ab")
    yield c
    c.close()


def _fill(conn, days: int, persistence_extra: int = 0):
    sharp, flat = dist.discretized_normal(7, 1), tuple([0.1] * 10)
    for i in range(days):
        _scored_day(conn, START + timedelta(days=i), {"mood": 6, "energy": 7, "soreness": 2},
                    {G: sharp, "persistence": flat, "climatology": flat})
    for i in range(persistence_extra):  # days only persistence scored
        _scored_day(conn, START + timedelta(days=days + i), {"mood": 6, "energy": 1, "soreness": 2},
                    {"persistence": flat})


def test_board_contains_no_per_day_values(conn):
    _fill(conn, 3)
    board = scoreboard.build(conn)
    text = json.dumps(board)
    dates = re.findall(r"\d{4}-\d\d-\d\d", text)
    assert set(dates) <= {board["generated_at"][:10]}
    assert '"day"' not in text and '"outcome"' not in text


def test_skill_is_paired(conn):
    _fill(conn, 4, persistence_extra=3)
    board = scoreboard.build(conn)
    row = next(r for r in board["forecasters"] if r["id"] == G and r["target"] == "energy")
    sharp, flat = dist.discretized_normal(7, 1), tuple([0.1] * 10)
    assert row["n"] == 4
    assert row["skill_vs_persistence"]["n"] == 4  # the 3 persistence-only days are excluded
    assert row["skill_vs_persistence"]["skill"] == pytest.approx(1 - dist.rps(sharp, 7) / dist.rps(flat, 7))


def test_primary_null_below_10(conn):
    _fill(conn, 9)
    primary = scoreboard.build(conn)["primary"]
    assert primary["forecaster"] == G and primary["target"] == "energy"
    assert primary["skill_vs_persistence"] is None and primary["n"] == 9
    assert primary["note"] == "n below 10"


def test_primary_interval_from_10(conn):
    _fill(conn, 10)
    point, lo, hi = scoreboard.build(conn)["primary"]["skill_vs_persistence"]
    assert lo <= point <= hi


def test_counts(conn):
    _fill(conn, 2)
    conn.execute("INSERT INTO snapshots VALUES ('2026-10-01', '{}', 'h', 't', '[]')")
    chain.append(conn, "2026-10-01", "void", {})
    board = scoreboard.build(conn)
    assert (board["days_locked"], board["days_scored"], board["days_voided"],
            board["days_no_outcome"]) == (3, 2, 1, 0)


def test_html_shows_n(conn):
    _fill(conn, 3)
    html = scoreboard.render_html(scoreboard.build(conn))
    assert "<script" not in html and "prefers-color-scheme" in html
    assert "n = 3" in html and "persistence" in html
    assert "published as-is" in html


def test_calibration_is_reproducible_across_row_order(tmp_path):
    """M3: randomized PIT draws are tied to rows by a fixed order."""
    boards = []
    for name, order in (("a", range(12)), ("b", reversed(range(12)))):
        c = make_db(tmp_path / f"{name}.db")
        chain.ensure_plan_hash(c, "ab")
        sharp = dist.discretized_normal(7, 1)
        for i in order:
            _scored_day(c, START + timedelta(days=i), {"mood": 6, "energy": 3 + i % 5, "soreness": 2},
                        {G: sharp, "persistence": tuple([0.1] * 10)})
        boards.append(scoreboard.build(c)["calibration"])
        c.close()
    assert boards[0] == boards[1]


def test_primary_pinned_to_original_gemini(conn, monkeypatch):
    """M4: a model change does not move the pre-registered primary endpoint."""
    monkeypatch.setattr(gemini, "FORECASTER_ID", "gemini:some-new-model")
    _fill(conn, 3)
    assert scoreboard.build(conn)["primary"]["forecaster"] == scoreboard.PRIMARY_FORECASTER
    assert scoreboard.PRIMARY_FORECASTER == "gemini:gemini-3.5-flash-lite"


def test_log_skill_columns_present(conn):
    """M5: log scores alongside RPS, with paired n."""
    _fill(conn, 4)
    row = next(r for r in scoreboard.build(conn)["forecasters"] if r["id"] == G and r["target"] == "energy")
    assert row["mean_log_score"] > 0
    assert row["log_skill_vs_persistence"]["n"] == 4 and row["log_skill_vs_persistence"]["skill"] > 0


def test_secondary_mood_soreness_and_7_vs_6(conn):
    _fill(conn, 12)
    sec = {(s["target"], s["forecaster"], s["reference"]): s for s in scoreboard.build(conn)["secondary"]}
    assert ("mood", G, "persistence") in sec and ("soreness", G, "persistence") in sec
    assert sec[("mood", G, "persistence")]["skill_vs_reference"] is not None  # n = 12 >= 10
    seven = sec[("energy", scoreboard.NOTES_FORECASTER, scoreboard.PRIMARY_FORECASTER)]
    assert seven["n"] == 0 and seven["skill_vs_reference"] is None


def test_7_vs_6_counts_none_yet_days_and_reports_days_with_notes(conn):
    sharp, flat = dist.discretized_normal(7, 1), tuple([0.1] * 10)
    n7 = scoreboard.NOTES_FORECASTER
    for i in range(11):
        d = START + timedelta(days=i)
        _scored_day(conn, d, {"mood": 6, "energy": 7, "soreness": 2}, {G: flat, n7: sharp})
        notes = "[]" if i < 6 else '[{"id": "h-1"}]'
        conn.execute("INSERT INTO lock_notes VALUES (?, ?, ?, 'h')", (d.isoformat(), n7, notes))
    seven = next(s for s in scoreboard.build(conn)["secondary"] if s["forecaster"] == n7)
    assert seven["n"] == 11 and seven["days_with_notes"] == 5
    assert seven["skill_vs_reference"] is not None


def test_html_shows_secondary_endpoints(conn):
    _fill(conn, 3)
    assert "Secondary endpoints" in scoreboard.render_html(scoreboard.build(conn))
