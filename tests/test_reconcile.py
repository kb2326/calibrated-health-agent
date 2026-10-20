"""Reconcile + daily rollup parity, with a fake service (no network)."""
from __future__ import annotations

from datetime import date

import pytest
from fakes import FakeService
from health_data import client, reconcile


def _steps_point(day: int, hour: int, count: str) -> dict:
    return {"steps": {"count": count, "interval": {
        "startTime": f"2026-10-{day:02d}T{hour:02d}:00:00Z",
        "endTime": f"2026-10-{day:02d}T{hour:02d}:01:00Z",
        "civilStartTime": {"date": {"year": 2026, "month": 10, "day": day},
                           "time": {"hours": hour, "minutes": 0}}}}}


def _bucket(day: int, count: str) -> dict:
    return {"civilStartTime": {"date": {"year": 2026, "month": 10, "day": day}},
            "steps": {"countSum": count}}


@pytest.fixture
def fake(monkeypatch):
    svc = FakeService({
        "reconcile": [
            {"dataPoints": [_steps_point(1, 8, "100"), _steps_point(1, 9, "50")],
             "nextPageToken": "t"},
            {"dataPoints": [_steps_point(2, 8, "200")]},
        ],
        "dailyRollUp": [{"rollupDataPoints": [_bucket(1, "150"), _bucket(2, "300")]}],
    })
    monkeypatch.setattr(client, "service", lambda: svc)
    return svc


def test_reconcile_uses_allowlisted_method(fake, monkeypatch):
    seen: list[str] = []
    real = client._read

    def spy(name, request):
        seen.append(name)
        return real(name, request)

    monkeypatch.setattr(client, "_read", spy)
    pts = list(reconcile.iter_reconciled("steps", date(2026, 10, 1), date(2026, 10, 3)))
    assert len(pts) == 3  # paginated across the page token
    assert set(seen) == {"dataPoints.reconcile"}
    assert "dataPoints.reconcile" in client.READ_METHODS


def test_reconcile_filter_is_civil_half_open(fake):
    list(reconcile.iter_reconciled("steps", date(2026, 10, 1), date(2026, 10, 3)))
    f = fake.points.calls[0][1]["filter"]
    assert 'steps.interval.civil_start_time >= "2026-10-01T00:00:00"' in f
    assert '< "2026-10-03T00:00:00"' in f


def test_daily_summed_reads_rollup(fake):
    got = reconcile.daily_summed("steps", date(2026, 10, 1), date(2026, 10, 3))
    assert got == {date(2026, 10, 1): 150.0, date(2026, 10, 2): 300.0}


def test_parity_report_pairs_rollup_with_summed_reconcile(fake):
    rows = reconcile.parity_report("steps", date(2026, 10, 1), date(2026, 10, 3))
    assert rows == [(date(2026, 10, 1), 150.0, 150.0), (date(2026, 10, 2), 300.0, 200.0)]


def test_parity_summary_counts_days_within_tolerance():
    rows = [(date(2026, 10, 1), 100.0, 101.0), (date(2026, 10, 2), 100.0, 80.0),
            (date(2026, 10, 3), 50.0, 0.0)]  # day 3: not worn per reconcile -> excluded
    assert reconcile.parity_summary(rows) == (1, 2)


def test_summed_types_constant():
    assert reconcile.SUMMED_TYPES == frozenset(
        {"steps", "distance", "total-calories", "active-minutes", "floors",
         "active-zone-minutes"})


def test_unsupported_reconcile_type_yields_empty_parity(fake):
    assert reconcile.parity_report("total-calories", date(2026, 10, 1), date(2026, 10, 3)) == []
