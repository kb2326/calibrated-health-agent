"""Hypotheses: checked in the sandbox when written, then judged only on later days."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from health_agents import hypotheses
from health_agents.hypotheses import Proposal
from health_ledger import chain
from ledger_fixtures import journal, make_db

START = date(2026, 8, 1)
COND = "def condition(days):\n    return days.tag_prev_late_meal == True\n"


def _day(i: int) -> date:
    return START + timedelta(days=i)


def _seed(conn, days: int, *, effect_until: int, late_every: int = 3):
    """Late meal every `late_every` days; energy the next day is 3 when i < effect_until."""
    for i in range(days):
        late = i % late_every == 0
        after_late = i % late_every == 1
        energy = 3 if (after_late and i < effect_until) else 7
        journal(conn, _day(i), 6, energy, 3, tags=["Late meal"] if late else [])
        chain.append(conn, _day(i).isoformat(), "outcome", {"d": i})
    conn.commit()


@pytest.fixture
def conn(tmp_path):
    return make_db(tmp_path / "h.db")


def _p(**over) -> Proposal:
    kw = dict(statement="energy tends to be lower after a late meal", target="energy",
              direction="lower", condition_code=COND)
    kw.update(over)
    return Proposal(**kw)


def test_valid_proposal_is_stored_with_receipts(conn):
    _seed(conn, 30, effect_until=99)
    hid, reason = hypotheses.validate(conn, _p(), _day(29))
    assert reason is None and hid and hid.startswith("h-")
    stmt, receipts_json = conn.execute(
        "SELECT statement, receipt_ids_json FROM hypotheses WHERE id = ?", (hid,)).fetchone()
    assert stmt.startswith("Association (n=10): energy tends to be lower when")
    assert receipts_json != "[]"
    status = conn.execute("SELECT status, n_cond FROM hypothesis_status WHERE hypothesis_id = ?",
                          (hid,)).fetchone()
    assert status == ("open", 10)


def test_condition_reading_an_outcome_column_fails(conn):
    _seed(conn, 30, effect_until=99)
    code = "def condition(days):\n    return days.energy < 5\n"
    hid, reason = hypotheses.validate(conn, _p(condition_code=code), _day(29))
    assert hid is None and "condition" in str(reason)


def test_too_few_or_too_many_matches_rejected(conn):
    _seed(conn, 30, effect_until=99)
    few = "def condition(days):\n    return days.day == days.day.max()\n"
    many = "def condition(days):\n    return days.weekday >= 0\n"
    assert "too few" in str(hypotheses.validate(conn, _p(condition_code=few), _day(29))[1])
    assert "too many" in str(hypotheses.validate(conn, _p(condition_code=many), _day(29))[1])


def test_disease_words_rejected(conn):
    _seed(conn, 30, effect_until=99)
    _, reason = hypotheses.validate(conn, _p(statement="late meals cause insomnia"), _day(29))
    assert "wording" in str(reason)


def test_duplicate_mask_rejected(conn):
    _seed(conn, 30, effect_until=99)
    assert hypotheses.validate(conn, _p(), _day(29))[1] is None
    same = "def condition(days):\n    return days.tag_prev_late_meal.fillna(False).astype(bool)\n"
    assert "duplicate" in str(hypotheses.validate(conn, _p(condition_code=same), _day(29))[1])


def test_retest_uses_only_days_after_creation(conn):
    _seed(conn, 30, effect_until=30)  # strong effect in sample only
    hid, _ = hypotheses.validate(conn, _p(), _day(29))
    for i in range(30, 70):  # no effect afterwards
        journal(conn, _day(i), 6, 7, 3, tags=["Late meal"] if i % 3 == 0 else [])
        chain.append(conn, _day(i).isoformat(), "outcome", {"d": i})
        conn.commit()
    hypotheses.retest(conn, _day(70))
    latest = conn.execute("SELECT status, n_cond FROM hypothesis_status WHERE hypothesis_id = ? "
                          "ORDER BY id DESC LIMIT 1", (hid,)).fetchone()
    assert latest[0] == "refuted" and latest[1] >= 10


def test_retest_supports_when_effect_holds(conn):
    _seed(conn, 60, effect_until=99)
    hid, _ = hypotheses.validate(conn, _p(), _day(29))  # created mid-way; days 30-59 out of sample
    out = hypotheses.retest(conn, _day(60))
    assert out["supported"] == 1
    assert [h["id"] for h in hypotheses.live(conn)] == [hid]


def test_retest_is_idempotent(conn):
    _seed(conn, 60, effect_until=99)
    hypotheses.validate(conn, _p(), _day(29))
    hypotheses.retest(conn, _day(60))
    n = conn.execute("SELECT COUNT(*) FROM hypothesis_status").fetchone()[0]
    assert hypotheses.retest(conn, _day(60))["tested"] == 0
    assert conn.execute("SELECT COUNT(*) FROM hypothesis_status").fetchone()[0] == n


def test_refuted_and_retired_not_live(conn):
    _seed(conn, 30, effect_until=99)
    hid, _ = hypotheses.validate(conn, _p(), _day(29))
    assert hid is not None and hypotheses.retire(conn, hid, _day(30)) is True
    assert hypotheses.live(conn) == []


def test_condition_cannot_read_outcomes_through_other_frames(conn):
    _seed(conn, 30, effect_until=99)
    code = ("def condition(days):\n"
            "    return days['day'].map(journal.set_index('date')['energy']) < 5\n")
    hid, reason = hypotheses.validate(conn, _p(condition_code=code), _day(29))
    assert hid is None and "condition" in str(reason)


def test_condition_receipt_reruns_on_the_lock_view(conn, monkeypatch, tmp_path):
    from health_agents import receipts
    from health_data import db
    path = tmp_path / "h.db"
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    c = make_db(path)
    _seed(c, 30, effect_until=99)
    hid, _ = hypotheses.validate(c, _p(), _day(29))
    c.commit()
    rid = json.loads(c.execute("SELECT receipt_ids_json FROM hypotheses WHERE id = ?",
                               (hid,)).fetchone()[0])[0]
    out = receipts.rerun(rid)
    assert out["matches"] and not out["data_changed"]
