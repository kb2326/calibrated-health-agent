"""The write guard on cha-data commands (fake storage injected; no network)."""
from __future__ import annotations

from contextlib import nullcontext

import pytest
from health_core.settings import Settings
from health_data import cli, store
from typer.testing import CliRunner

runner = CliRunner()


class _Conn:
    def execute(self, _query):
        return self

    def fetchone(self):
        return (1,)


@pytest.fixture
def calls(monkeypatch):
    log: list[str] = []
    monkeypatch.setattr(store, "require_fresh", lambda *a, **k: log.append("fresh"))
    monkeypatch.setattr(store, "push_recorded", lambda *a, **k: log.append("push"))
    monkeypatch.setattr(cli.db, "connect", lambda: nullcontext(_Conn()))
    return log


def _settings(monkeypatch, bucket):
    monkeypatch.setattr(cli, "get_settings", lambda: Settings.model_validate({"db_bucket": bucket}))


def test_guard_wraps_write_with_fresh_and_push(monkeypatch, calls):
    _settings(monkeypatch, "bkt")
    monkeypatch.setattr(cli.db, "init_db", lambda: calls.append("write"))
    result = runner.invoke(cli.app, ["db", "migrate"])
    assert result.exit_code == 0, result.output
    assert calls == ["fresh", "write", "push"]


def test_guard_is_noop_without_bucket(monkeypatch, calls):
    _settings(monkeypatch, None)
    monkeypatch.setattr(cli.db, "init_db", lambda: calls.append("write"))
    assert runner.invoke(cli.app, ["db", "migrate"]).exit_code == 0
    assert calls == ["write"]


def test_stale_blocks_write_with_one_line(monkeypatch, calls):
    _settings(monkeypatch, "bkt")

    def stale(*a, **k):
        raise store.StaleLocalDbError("local db is stale; run cha-data db pull")

    monkeypatch.setattr(store, "require_fresh", stale)
    monkeypatch.setattr(cli.db, "init_db", lambda: calls.append("write"))
    result = runner.invoke(cli.app, ["db", "migrate"])
    assert result.exit_code == 1 and "stale" in result.output
    assert calls == []


def test_failed_command_does_not_push(monkeypatch, calls):
    _settings(monkeypatch, "bkt")

    def boom():
        raise RuntimeError("x")

    monkeypatch.setattr(cli.db, "init_db", boom)
    assert runner.invoke(cli.app, ["db", "migrate"]).exit_code != 0
    assert "push" not in calls
