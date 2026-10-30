"""The eval fixture: the smoke database plus the hard cases evals need."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest
from health_eval import fixture


@pytest.fixture
def path(tmp_path):
    return fixture.build(tmp_path / "health.db")


def test_fixture_has_gap_and_missing_metric(path):
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM daily_metrics WHERE data_type = 'vo2-max'").fetchone()[0] == 0
    days = {date.fromisoformat(d) for (d,) in conn.execute(
        "SELECT date FROM daily_metrics WHERE data_type = 'sleep'")}
    gap = fixture.gap_days()
    assert len(gap) == 5 and all(d not in days for d in gap)
    assert all(b - a == timedelta(days=1) for a, b in zip(gap, gap[1:], strict=False))


def test_fixture_has_red_flag_and_poisoned_device(path):
    conn = sqlite3.connect(path)
    notes = [n for (n,) in conn.execute("SELECT note FROM journal_submissions WHERE note IS NOT NULL")]
    assert any("chest pain" in n for n in notes)
    names = [n for (n,) in conn.execute("SELECT display_name FROM devices")]
    assert any(fixture.POISON_DEVICE in n for n in names)


def test_truth_sql_reads_the_fixture(path, monkeypatch):
    assert fixture.truth(path, "SELECT COUNT(*) AS n FROM journal_outcome") == fixture.JOURNAL_DAYS


def test_truth_sql_is_read_only(path):
    with pytest.raises(Exception):
        fixture.truth(path, "DELETE FROM daily_metrics")


def test_fixture_is_deterministic(tmp_path):
    a, b = fixture.build(tmp_path / "a.db"), fixture.build(tmp_path / "b.db")
    q = "SELECT date, data_type, agg_value FROM daily_metrics ORDER BY 1, 2"
    assert sqlite3.connect(a).execute(q).fetchall() == sqlite3.connect(b).execute(q).fetchall()
