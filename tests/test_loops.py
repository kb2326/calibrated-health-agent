"""Tests for loop termination and analysis statistics.

The pagination loop once ran for hours because its only exit condition was
one the server controlled, and the server never satisfied it. These tests
pin down the properties that make the loops safe to run unattended:
bounded, idempotent, and refusing to score a partial day.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from health_data import client


class _StubPointsApi:
    """A dataPoints API that mimics the real server's pagination behaviour."""

    def __init__(self, pages):
        self._pages = list(pages)
        self.calls = 0

    def list(self, **kwargs):
        return {"_stub": True}

    def list_next(self, previous_request, previous_response):
        return {"_stub": True}

    def take(self):
        self.calls += 1
        if self._pages:
            return self._pages.pop(0)
        # The real API keeps offering a token forever once exhausted.
        return {"dataPoints": [], "nextPageToken": "always-another-page"}


@pytest.fixture
def stub_pagination(monkeypatch):
    """Wire client._read and the service to a scripted page sequence."""

    def _install(pages):
        api = _StubPointsApi(pages)

        class _Svc:
            def users(self):
                return self

            def dataTypes(self):
                return self

            def dataPoints(self):
                return api

        monkeypatch.setattr(client, "service", lambda: _Svc())
        monkeypatch.setattr(client, "_read", lambda name, request: api.take())
        return api

    return _install


class TestPaginationTermination:
    def test_terminates_when_token_finally_empties(self, stub_pagination):
        api = stub_pagination([
            {"dataPoints": [{"a": 1}], "nextPageToken": "t1"},
            {"dataPoints": [{"a": 2}], "nextPageToken": ""},
        ])
        got = list(client._iter_window("weight", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"))
        assert len(got) == 2
        assert api.calls == 2

    def test_terminates_against_an_endless_token(self, stub_pagination):
        # This is the real failure: a server that always returns a token.
        # Without a self-owned exit condition the loop never stops.
        api = stub_pagination([{"dataPoints": [{"a": 1}], "nextPageToken": "t1"}])
        got = list(client._iter_window("weight", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"))
        assert len(got) == 1
        assert api.calls <= 1 + client.MAX_EMPTY_PAGES, (
            "must stop after a short run of empty pages, not chase the token"
        )

    def test_page_cap_is_an_absolute_backstop(self, stub_pagination):
        # Pages that always carry one point never trip the empty-streak
        # guard, so max_pages is the only thing that can stop this.
        never_empty = [{"dataPoints": [{"a": i}], "nextPageToken": "t"} for i in range(50)]
        api = stub_pagination(never_empty)
        got = list(client._iter_window(
            "weight", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z", max_pages=5
        ))
        assert api.calls == 5
        assert len(got) == 5

    def test_empty_streak_resets_on_a_non_empty_page(self, stub_pagination):
        pages = [
            {"dataPoints": [], "nextPageToken": "t"},
            {"dataPoints": [], "nextPageToken": "t"},
            {"dataPoints": [{"a": 1}], "nextPageToken": "t"},  # resets the streak
            {"dataPoints": [], "nextPageToken": ""},
        ]
        stub_pagination(pages)
        got = list(client._iter_window("weight", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"))
        assert len(got) == 1, "a sparse page in the middle must not end the scan"


class TestAnalysisStatistics:
    """analyze.py's scoring rules, exercised against a temporary database."""

    @pytest.fixture
    def analyze_on(self, tmp_path, monkeypatch):
        import importlib

        from health_data import db

        monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
        db.init_db()
        analyze = importlib.import_module("health_data.legacy.analyze")
        importlib.reload(analyze)

        def _seed(data_type, values, end_day):
            with db.connect() as conn:
                for i, v in enumerate(reversed(values)):
                    d = (end_day - timedelta(days=i)).isoformat()
                    conn.execute(
                        "INSERT OR REPLACE INTO daily_metrics VALUES (?,?,?,1)",
                        (d, data_type, float(v)),
                    )

        return analyze, _seed

    def test_flat_baseline_reports_no_variance_not_a_huge_z(self, analyze_on):
        # pstdev of a constant series is 0. Dividing by a 1e-9 floor produced
        # z of ~1e9 and a permanent alert on the most stable metrics.
        analyze, seed = analyze_on
        day = date(2026, 8, 20)
        seed("weight", [80.0] * 10 + [80.0], day)
        out = analyze.run(target_date=day.isoformat())
        assert out["weight"]["severity"] == "no_variance"
        assert out["weight"]["z_score"] is None

    def test_obvious_outlier_is_flagged(self, analyze_on):
        analyze, seed = analyze_on
        day = date(2026, 8, 20)
        seed("steps", [5000, 5200, 4800, 5100, 4900, 5050, 5150, 4950, 5000, 100], day)
        out = analyze.run(target_date=day.isoformat())
        assert out["steps"]["severity"] in ("watch", "alert")
        assert out["steps"]["z_score"] < 0

    def test_short_history_is_insufficient_rather_than_scored(self, analyze_on):
        analyze, seed = analyze_on
        day = date(2026, 8, 20)
        seed("steps", [5000, 5100, 4900], day)
        out = analyze.run(target_date=day.isoformat())
        assert out["steps"]["severity"] == "insufficient_data"

    def test_default_target_is_a_complete_day(self, analyze_on):
        # Scoring the current date meant a part-finished day read as a large
        # negative anomaly every single morning.
        analyze, _ = analyze_on
        assert analyze._last_complete_day(None) == (date.today() - timedelta(days=1)).isoformat()
