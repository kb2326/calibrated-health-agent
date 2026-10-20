"""The sync job: step order, push rules, structured logs (fakes only, no network)."""
from __future__ import annotations

import json

import pytest
from health_core.settings import Settings
from health_data import auth, db, store, sync
from jobs import sync_job


@pytest.fixture
def calls(monkeypatch, tmp_path):
    log: list[str] = []
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "health.db")
    monkeypatch.setattr(
        sync_job, "get_settings", lambda: Settings.model_validate({"db_bucket": "bkt", "journal_form_id": "f"}))
    monkeypatch.setattr(store, "pull_db", lambda *a, **k: log.append("pull") or 5)
    monkeypatch.setattr(sync_job, "_migrate", lambda: log.append("migrate") or {})
    monkeypatch.setattr(sync, "run", lambda: log.append("sync") or {"steps": {"fetched": 1, "inserted": 1}})
    monkeypatch.setattr(sync_job, "_journal_import", lambda s: log.append("import") or {})
    monkeypatch.setattr(store, "push_recorded", lambda *a, **k: log.append("push") or 6)
    return log


def _lines(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_job_happy_path_order(calls, capsys):
    assert sync_job.main([]) == 0
    assert calls == ["pull", "migrate", "sync", "import", "push"]
    lines = _lines(capsys)
    assert [line["step"] for line in lines] == ["pull", "migrate", "sync", "journal", "push"]
    assert {line["severity"] for line in lines} == {"INFO"}


def test_job_exit_nonzero_on_reauth(calls, monkeypatch, capsys):
    def reauth():
        raise auth.ReauthRequired("Run `cha-data auth login` then `cha-data auth push-secret`")

    monkeypatch.setattr(sync, "run", reauth)
    assert sync_job.main([]) == 1
    assert "push" not in calls and "import" not in calls
    last = _lines(capsys)[-1]
    assert last["severity"] == "ERROR" and last["step"] == "sync"


def test_job_nonzero_on_concurrent_update(calls, monkeypatch, capsys):
    def clash(*a, **k):
        raise store.ConcurrentUpdateError("changed")

    monkeypatch.setattr(store, "push_recorded", clash)
    assert sync_job.main([]) == 1
    last = _lines(capsys)[-1]
    assert last["severity"] == "ERROR" and last["step"] == "push"


def test_partial_sync_pushes_then_fails(calls, monkeypatch, capsys):
    monkeypatch.setattr(sync, "run", lambda: calls.append("sync") or {"steps": {"error": "boom"}})
    assert sync_job.main([]) == 1
    assert calls[-1] == "push"
    assert any(line["severity"] == "ERROR" for line in _lines(capsys))


def test_journal_failure_still_pushes_sync_work(calls, monkeypatch, capsys):
    def boom(_s):
        raise RuntimeError("x")

    monkeypatch.setattr(sync_job, "_journal_import", boom)
    assert sync_job.main([]) == 1
    assert calls[-1] == "push"
    assert any(x["severity"] == "ERROR" and x["step"] == "journal" for x in _lines(capsys))


def test_failed_pull_runs_nothing_downstream(calls, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("gcs down")

    monkeypatch.setattr(store, "pull_db", boom)
    assert sync_job.main([]) == 1
    assert calls == []
    lines = _lines(capsys)
    assert len(lines) == 1 and lines[0]["severity"] == "ERROR" and lines[0]["step"] == "pull"


def test_empty_sync_summary_is_an_error(calls, monkeypatch, capsys):
    monkeypatch.setattr(sync, "run", lambda: calls.append("sync") or {})
    assert sync_job.main([]) == 1
    assert "push" not in calls
    assert any(x["severity"] == "ERROR" and x["step"] == "sync" for x in _lines(capsys))


def test_dry_run_never_pushes(calls):
    assert sync_job.main(["--dry-run"]) == 0
    assert "push" not in calls and calls[:2] == ["pull", "migrate"]


def test_synthetic_dry_run_skips_everything_remote(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "x.db")
    monkeypatch.setattr(sync_job, "get_settings", lambda: Settings.model_validate({"data_mode": "synthetic"}))
    monkeypatch.setattr(store, "pull_db", lambda *a, **k: pytest.fail("network"))
    monkeypatch.setattr(sync, "run", lambda: pytest.fail("network"))
    assert sync_job.main(["--dry-run"]) == 0
    assert "skipped (synthetic)" in capsys.readouterr().out
