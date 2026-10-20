"""The write guard and db pull/push on cha-data (fake storage injected; no network)."""
from __future__ import annotations

from contextlib import nullcontext

import pytest
from health_core.settings import Settings
from health_data import cli, store
from test_store import FakeClient, _db
from typer.testing import CliRunner

runner = CliRunner()


class _Conn:
    def execute(self, _query):
        return self

    def fetchone(self):
        return (1,)


@pytest.fixture
def calls(monkeypatch, tmp_path):
    log: list[str] = []
    monkeypatch.setattr(cli.db, "DB_PATH", tmp_path / "health.db")
    monkeypatch.setattr(store, "require_fresh", lambda *a, **k: log.append("fresh"))
    monkeypatch.setattr(store, "push_recorded", lambda *a, **k: log.append("push"))
    monkeypatch.setattr(cli.db, "connect", lambda: nullcontext(_Conn()))
    return log


def _settings(monkeypatch, bucket):
    monkeypatch.setattr(cli, "get_settings", lambda: Settings.model_validate({"db_bucket": bucket}))


def _write(calls):
    def write():
        calls.append("write")
        cli.db.DB_PATH.write_bytes(b"changed" * (len(calls) + 1))

    return write


def test_guard_wraps_write_with_fresh_and_push(monkeypatch, calls):
    _settings(monkeypatch, "bkt")
    monkeypatch.setattr(cli.db, "init_db", _write(calls))
    result = runner.invoke(cli.app, ["db", "migrate"])
    assert result.exit_code == 0, result.output
    assert calls == ["fresh", "write", "push"]


def test_guard_is_noop_without_bucket(monkeypatch, calls):
    _settings(monkeypatch, None)
    monkeypatch.setattr(cli.db, "init_db", _write(calls))
    assert runner.invoke(cli.app, ["db", "migrate"]).exit_code == 0
    assert calls == ["write"]


def test_stale_blocks_write_with_one_line(monkeypatch, calls):
    _settings(monkeypatch, "bkt")

    def stale(*a, **k):
        raise store.StaleLocalDbError("local db is stale; run cha-data db pull")

    monkeypatch.setattr(store, "require_fresh", stale)
    monkeypatch.setattr(cli.db, "init_db", _write(calls))
    result = runner.invoke(cli.app, ["db", "migrate"])
    assert result.exit_code == 1 and "stale" in result.output
    assert calls == []


def test_failed_command_does_not_push(monkeypatch, calls):
    _settings(monkeypatch, "bkt")

    def boom():
        cli.db.DB_PATH.write_bytes(b"half written")
        raise RuntimeError("x")

    monkeypatch.setattr(cli.db, "init_db", boom)
    assert runner.invoke(cli.app, ["db", "migrate"]).exit_code != 0
    assert "push" not in calls


def test_partial_sync_exit_is_pushed_and_keeps_exit_code(monkeypatch, calls):
    from health_data import sync

    _settings(monkeypatch, "bkt")

    def partial():
        calls.append("write")
        cli.db.DB_PATH.write_bytes(b"some types synced")
        return {"a": {"inserted": 1}, "b": {"error": "boom"}}

    monkeypatch.setattr(sync, "run", partial)
    result = runner.invoke(cli.app, ["sync"])
    assert result.exit_code == 1
    assert calls == ["fresh", "write", "push"]


def test_exit_before_writing_does_not_push(monkeypatch, calls):
    from health_data import auth, sync

    _settings(monkeypatch, "bkt")

    def no_auth():
        raise auth.AuthError("not logged in")

    monkeypatch.setattr(sync, "run", no_auth)
    result = runner.invoke(cli.app, ["sync"])
    assert result.exit_code == 1
    assert calls == ["fresh"]


def test_concurrent_update_on_push_is_one_line_exit_1(monkeypatch, tmp_path):
    client = FakeClient()
    client.b.objects["health.db"] = (b"theirs", 9)
    monkeypatch.setattr(store, "_client", lambda c: client)
    monkeypatch.setattr(cli.db, "DB_PATH", tmp_path / "health.db")
    monkeypatch.setattr(store, "recorded_generation", lambda gen_path=None: 5)
    monkeypatch.setattr(store, "require_fresh", lambda *a, **k: None)
    monkeypatch.setattr(cli.db, "init_db", lambda: _db(cli.db.DB_PATH))
    monkeypatch.setattr(cli.db, "connect", lambda: nullcontext(_Conn()))
    _settings(monkeypatch, "bkt")
    result = runner.invoke(cli.app, ["db", "migrate"])
    assert result.exit_code == 1 and "db error:" in result.output
    assert client.b.objects["health.db"] == (b"theirs", 9)


def test_db_pull_and_push_happy_path(monkeypatch, tmp_path):
    client = FakeClient()
    client.b.objects["health.db"] = (b"remote", 7)
    monkeypatch.setattr(store, "_client", lambda c: client)
    monkeypatch.setattr(cli.db, "DB_PATH", tmp_path / "health.db")
    monkeypatch.setattr(store, "_gen_path", lambda p: tmp_path / ".db_generation")
    _settings(monkeypatch, "bkt")
    pulled = runner.invoke(cli.app, ["db", "pull"])
    assert pulled.exit_code == 0 and "7" in pulled.output
    assert (tmp_path / "health.db").read_bytes() == b"remote"
    (tmp_path / "health.db").unlink()
    _db(tmp_path / "health.db")  # a real sqlite file to push
    pushed = runner.invoke(cli.app, ["db", "push"])
    assert pushed.exit_code == 0 and "pushed generation 101" in pushed.output
    assert client.b.uploads[-1][1] == 7


@pytest.mark.parametrize("sub", ["pull", "push"])
def test_db_pull_push_require_bucket(monkeypatch, sub):
    _settings(monkeypatch, None)
    result = runner.invoke(cli.app, ["db", sub])
    assert result.exit_code != 0 and "CHA_DB_BUCKET is not set" in result.output


def test_same_size_write_with_equal_mtime_is_still_pushed(monkeypatch, calls):
    import os

    _settings(monkeypatch, "bkt")
    path = cli.db.DB_PATH
    path.write_bytes(b"value=1111")
    st = path.stat()

    def write():
        path.write_bytes(b"value=2222")  # same size
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))  # same mtime

    monkeypatch.setattr(cli.db, "init_db", write)
    assert runner.invoke(cli.app, ["db", "migrate"]).exit_code == 0
    assert calls == ["fresh", "push"]


@pytest.mark.parametrize("error", [RuntimeError("database busy"), FileNotFoundError("gone")])
def test_push_runtime_errors_become_one_line(monkeypatch, calls, error):
    _settings(monkeypatch, "bkt")
    monkeypatch.setattr(cli.db, "init_db", _write(calls))

    def fail(*a, **k):
        raise error

    monkeypatch.setattr(store, "push_recorded", fail)
    result = runner.invoke(cli.app, ["db", "migrate"])
    assert result.exit_code == 1
    assert f"db error: {type(error).__name__}: {error}" in result.output
    assert "Traceback" not in result.output
