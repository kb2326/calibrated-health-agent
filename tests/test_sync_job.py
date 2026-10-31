"""The sync job: step order, push rules, structured logs (fakes only, no network)."""
from __future__ import annotations

import json
import sqlite3

import pytest
from health_core.settings import Settings
from health_data import auth, db, store, sync
from jobs import sync_job


class Calls(list[str]):
    """Step names in call order, plus every heartbeat the job wrote."""

    def __init__(self):
        super().__init__()
        self.beats: list[dict] = []


@pytest.fixture
def calls(monkeypatch, tmp_path):
    log = Calls()
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "health.db")
    monkeypatch.setattr(
        sync_job, "get_settings", lambda: Settings.model_validate({
            "db_bucket": "bkt", "journal_form_id": "f", "ledger_bucket": "lb",
            "ledger_repo": "git@github.com:kb2326/cha-ledger-log.git", "ledger_key_secret": "k"}))
    monkeypatch.setattr(store, "pull_db", lambda *a, **k: log.append("pull") or 5)
    monkeypatch.setattr(sync_job, "_migrate", lambda: log.append("migrate") or {})
    monkeypatch.setattr(sync, "run", lambda: log.append("sync") or {"steps": {"fetched": 1, "inserted": 1}})
    monkeypatch.setattr(sync_job, "_journal_import", lambda s: log.append("import") or {})
    monkeypatch.setattr(sync_job, "_derive", lambda: log.append("derive") or {"rows": {}})
    monkeypatch.setattr(store, "push_recorded", lambda *a, **k: log.append("push") or 6)
    monkeypatch.setattr(sync_job, "_lock", lambda s: log.append("lock") or {"written": False})
    monkeypatch.setattr(sync_job, "_settle", lambda: log.append("settle") or {"written": False})
    monkeypatch.setattr(sync_job, "_retest", lambda: log.append("retest") or {"tested": 0})
    monkeypatch.setattr(sync_job, "_investigate",
                        lambda: log.append("investigate") or {"result": "skipped (nothing new)"})
    monkeypatch.setattr(sync_job, "_agent_seq", lambda: (0, 0))
    monkeypatch.setattr(sync_job, "_publish", lambda s: log.append("publish") or {})
    monkeypatch.setattr(store, "read_heartbeat", lambda *a, **k: None)
    monkeypatch.setattr(store, "write_heartbeat", lambda b, o, beat, **k: log.append("heartbeat") or log.beats.append(beat))
    return log


def _lines(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def _step(lines, name):
    return next(x for x in lines if x["step"] == name)


def _interrupted(committed: dict, cause: Exception):
    def run():
        raise sync.SyncInterrupted(committed) from cause
    return run


def test_job_happy_path_order(calls, capsys):
    assert sync_job.main([]) == 0
    assert calls == ["pull", "migrate", "sync", "import", "derive", "lock", "settle", "retest",
                     "investigate", "push", "publish", "heartbeat"]
    lines = _lines(capsys)
    assert [line["step"] for line in lines] == [
        "pull", "migrate", "sync", "journal", "derive", "lock", "settle", "retest", "investigate", "push",
        "publish", "heartbeat"]
    assert {line["severity"] for line in lines} == {"INFO"}


def test_job_exit_nonzero_on_reauth(calls, monkeypatch, capsys):
    def reauth():
        raise auth.ReauthRequired("Run `cha-data auth login` then `cha-data auth push-secret`")

    monkeypatch.setattr(sync, "run", reauth)
    assert sync_job.main([]) == 1
    assert "push" not in calls and "import" in calls  # journal still runs; nothing pushed
    lines = _lines(capsys)
    assert any(x["severity"] == "ERROR" and x["step"] == "sync" for x in lines)
    assert "skipped" in _step(lines, "push")["result"]


def test_job_nonzero_on_concurrent_update(calls, monkeypatch, capsys):
    def clash(*a, **k):
        raise store.ConcurrentUpdateError("changed")

    monkeypatch.setattr(store, "push_recorded", clash)
    assert sync_job.main([]) == 1
    assert _step(_lines(capsys), "push")["severity"] == "ERROR"
    assert calls.beats[-1]["ok"] is False and calls.beats[-1]["pushed"] is False


def test_partial_sync_pushes_then_fails(calls, monkeypatch, capsys):
    monkeypatch.setattr(sync, "run", lambda: calls.append("sync") or {
        "steps": {"error": "boom"}, "sleep": {"fetched": 2, "inserted": 1}})
    assert sync_job.main([]) == 1
    assert "push" in calls
    assert any(line["severity"] == "ERROR" for line in _lines(capsys))


def test_journal_failure_still_pushes_sync_work(calls, monkeypatch, capsys):
    def boom(_s):
        raise RuntimeError("answer 7 leaked?")

    monkeypatch.setattr(sync_job, "_journal_import", boom)
    assert sync_job.main([]) == 1
    assert "push" in calls
    line = next(x for x in _lines(capsys) if x["step"] == "journal")
    assert line == {"severity": "ERROR", "step": "journal", "error": "RuntimeError", "response_id": None}


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
    assert any(x["severity"] == "ERROR" and x["step"] == "sync" for x in _lines(capsys))


def test_sync_exception_still_imports_journal_and_pushes_committed_rows(calls, monkeypatch, capsys):
    monkeypatch.setattr(sync, "run", _interrupted({"steps": {"fetched": 3, "inserted": 2}}, RuntimeError("bug")))
    assert sync_job.main([]) == 1
    assert calls == ["pull", "migrate", "import", "derive", "lock", "settle", "retest", "investigate",
                     "push", "publish", "heartbeat"]
    line = _step(_lines(capsys), "sync")
    assert (line["severity"], line["error"], line["changed_rows"]) == ("ERROR", "RuntimeError", 2)


def test_sync_exception_with_nothing_committed_skips_push(calls, monkeypatch, capsys):
    # A network outage mid-run must not mint a new bucket generation every hour.
    monkeypatch.setattr(sync, "run", _interrupted({"steps": {"fetched": 9, "inserted": 0}}, ConnectionError("down")))
    monkeypatch.setattr(sync_job, "_journal_import", lambda s: calls.append("import") or {"new_submissions": 0})
    assert sync_job.main([]) == 1
    assert "push" not in calls
    assert _step(_lines(capsys), "push")["result"] == "skipped (no data changed)"


def test_database_error_never_pushes(calls, monkeypatch, capsys):
    # A damaged or unreadable file must never replace the good copy in the bucket.
    monkeypatch.setattr(sync, "run", _interrupted({"steps": {"inserted": 5}}, sqlite3.DatabaseError("malformed")))
    monkeypatch.setattr(sync_job, "_journal_import", lambda s: calls.append("import") or {"new_submissions": 1})
    assert sync_job.main([]) == 1
    assert "push" not in calls
    assert "database error" in _step(_lines(capsys), "push")["result"]


def test_failed_migrate_runs_nothing_downstream(calls, monkeypatch, capsys):
    def boom():
        raise RuntimeError("bad schema")

    monkeypatch.setattr(sync_job, "_migrate", boom)
    assert sync_job.main([]) == 1
    assert calls == ["pull"]


def test_push_skipped_when_no_data_changed(calls, monkeypatch, capsys):
    monkeypatch.setattr(sync, "run", lambda: calls.append("sync") or {
        "steps": {"fetched": 9, "inserted": 0}, "_devices": {"error": "403"}})
    monkeypatch.setattr(sync_job, "_journal_import", lambda s: calls.append("import") or {"new_submissions": 0})
    assert sync_job.main([]) == 0  # the device failure is not a failure
    assert "push" not in calls
    assert _step(_lines(capsys), "push") == {"severity": "INFO", "step": "push", "result": "skipped (no data changed)"}
    beat = calls.beats[-1]  # N1: a skipped push still records that the data was checked
    assert beat["ok"] is True and beat["pushed"] is False and beat["last_ok_at"] == beat["checked_at"]


def test_new_journal_submission_alone_is_pushed(calls, monkeypatch):
    monkeypatch.setattr(sync, "run", lambda: calls.append("sync") or {"steps": {"fetched": 9, "inserted": 0}})
    monkeypatch.setattr(sync_job, "_journal_import", lambda s: calls.append("import") or {"new_submissions": 1})
    assert sync_job.main([]) == 0
    assert "push" in calls


def test_journal_error_log_has_type_and_response_id_only(calls, monkeypatch, capsys):
    from health_data.journal_import import JournalImportError

    def boom(_s):
        raise JournalImportError("ValueError", "resp-42")

    monkeypatch.setattr(sync_job, "_journal_import", boom)
    assert sync_job.main([]) == 1
    line = next(x for x in _lines(capsys) if x["step"] == "journal")
    assert line == {"severity": "ERROR", "step": "journal", "error": "ValueError", "response_id": "resp-42"}


def test_db_path_restored_after_dry_run(calls):
    before = db.DB_PATH
    sync_job.main(["--dry-run"])
    assert db.DB_PATH == before


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


def test_heartbeat_reports_the_run(calls):
    assert sync_job.main([]) == 0
    beat = calls.beats[-1]
    assert beat["ok"] is True and beat["pushed"] is True and beat["db_generation"] == 6
    assert beat["changed_rows"] == 1 and beat["last_ok_at"] == beat["checked_at"]


def test_failed_run_heartbeat_keeps_previous_last_ok(calls, monkeypatch):
    monkeypatch.setattr(store, "read_heartbeat", lambda *a, **k: {"last_ok_at": "2026-10-20T00:00:00.000000Z"})
    monkeypatch.setattr(sync, "run", lambda: calls.append("sync") or {"steps": {"error": "boom"}})
    assert sync_job.main([]) == 1
    beat = calls.beats[-1]
    assert beat["ok"] is False and beat["last_ok_at"] == "2026-10-20T00:00:00.000000Z"


def test_unreadable_previous_heartbeat_is_not_fatal(calls, monkeypatch):
    def boom(*a, **k):
        raise ValueError("bad json")

    monkeypatch.setattr(store, "read_heartbeat", boom)
    assert sync_job.main([]) == 0
    assert calls.beats[-1]["ok"] is True


def test_heartbeat_write_failure_fails_the_job(calls, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("gcs down")

    monkeypatch.setattr(store, "write_heartbeat", boom)
    assert sync_job.main([]) == 1
    assert _step(_lines(capsys), "heartbeat")["severity"] == "ERROR"


def test_dry_run_writes_no_heartbeat(calls):
    sync_job.main(["--dry-run"])
    assert "heartbeat" not in calls


def test_publish_runs_only_after_successful_push(calls, monkeypatch):
    def clash(*a, **k):
        raise store.ConcurrentUpdateError("changed")

    monkeypatch.setattr(store, "push_recorded", clash)
    assert sync_job.main([]) == 1
    assert "publish" not in calls and calls[-1] == "heartbeat"


def test_publish_retries_when_nothing_changed(calls, monkeypatch):
    monkeypatch.setattr(sync, "run", lambda: calls.append("sync") or {"steps": {"inserted": 0}})
    monkeypatch.setattr(sync_job, "_journal_import", lambda s: calls.append("import") or {"new_submissions": 0})
    assert sync_job.main([]) == 0
    assert "push" not in calls and "publish" in calls


def test_auth_failure_still_locks_and_keeps_the_lock(calls, monkeypatch):
    def reauth():
        raise auth.ReauthRequired("login")

    monkeypatch.setattr(sync, "run", reauth)
    seqs = iter([1, 2])  # the lock appended a chain entry
    monkeypatch.setattr(sync_job, "_ledger_seq", lambda: next(seqs))
    assert sync_job.main([]) == 1
    assert calls[calls.index("lock") + 1:calls.index("lock") + 6] == [
        "settle", "retest", "investigate", "push", "publish"]


def test_database_error_skips_ledger(calls, monkeypatch, capsys):
    monkeypatch.setattr(sync, "run", _interrupted({}, sqlite3.DatabaseError("malformed")))
    assert sync_job.main([]) == 1
    assert "lock" not in calls and "settle" not in calls and "publish" not in calls
    assert "database error" in _step(_lines(capsys), "lock")["result"]


def test_ledger_rows_trigger_push(calls, monkeypatch):
    monkeypatch.setattr(sync, "run", lambda: calls.append("sync") or {"steps": {"inserted": 0}})
    monkeypatch.setattr(sync_job, "_journal_import", lambda s: calls.append("import") or {"new_submissions": 0})
    seqs = iter([3, 4])  # settle appended a chain entry
    monkeypatch.setattr(sync_job, "_ledger_seq", lambda: next(seqs))
    assert sync_job.main([]) == 0
    assert "push" in calls


def test_lock_failure_fails_run_but_keeps_other_work(calls, monkeypatch, capsys):
    def boom(_s):
        raise RuntimeError("vertex down")

    monkeypatch.setattr(sync_job, "_lock", boom)
    assert sync_job.main([]) == 1
    assert "push" in calls and "settle" in calls
    assert _step(_lines(capsys), "lock")["severity"] == "ERROR"


def test_dry_run_skips_ledger(calls):
    sync_job.main(["--dry-run"])
    assert not {"lock", "settle", "retest", "investigate", "publish"} & set(calls)


def test_publish_skipped_without_ledger_settings(calls, monkeypatch, capsys):
    monkeypatch.setattr(sync_job, "get_settings", lambda: Settings.model_validate(
        {"db_bucket": "bkt", "journal_form_id": "f"}))
    assert sync_job.main([]) == 0
    assert "publish" not in calls
    assert "not set" in _step(_lines(capsys), "publish")["result"]


def test_heartbeat_reports_lock(calls, monkeypatch):
    monkeypatch.setattr(sync_job, "_locked_today", lambda: True)
    sync_job.main([])
    assert calls.beats[-1]["locked_today"] is True


def test_partial_settle_is_still_pushed(calls, monkeypatch):
    # settle committed one day, then raised: the bucket must get that day before publish
    seqs = iter([5, 6])
    monkeypatch.setattr(sync_job, "_ledger_seq", lambda: next(seqs))
    monkeypatch.setattr(sync, "run", lambda: calls.append("sync") or {"steps": {"inserted": 0}})
    monkeypatch.setattr(sync_job, "_journal_import", lambda s: calls.append("import") or {"new_submissions": 0})

    def half(_=None):
        calls.append("settle")
        raise RuntimeError("second day failed")

    monkeypatch.setattr(sync_job, "_settle", half)
    assert sync_job.main([]) == 1
    assert calls.index("push") < calls.index("publish")


def test_investigator_failure_does_not_fail_the_job(calls, monkeypatch, capsys):
    monkeypatch.setattr(sync_job, "_investigate", lambda: calls.append("investigate") or {
        "result": "failed", "error": "RuntimeError"})
    assert sync_job.main([]) == 0
    lines = _lines(capsys)
    warning = [x for x in lines if x["step"] == "investigate" and x["severity"] == "WARNING"]
    assert warning and warning[0]["error"] == "RuntimeError"
    assert "push" in calls


def test_retest_exception_fails_the_run_but_keeps_other_work(calls, monkeypatch):
    def boom():
        raise RuntimeError("bug")
    monkeypatch.setattr(sync_job, "_retest", boom)
    assert sync_job.main([]) == 1
    assert "investigate" in calls and "push" in calls


def test_dry_run_skips_retest_and_investigate(calls):
    sync_job.main(["--dry-run"])
    assert not {"retest", "investigate"} & set(calls)


def test_agent_rows_count_as_changes_for_push(calls, monkeypatch):
    monkeypatch.setattr(sync, "run", lambda: calls.append("sync") or {"steps": {"fetched": 0}})
    monkeypatch.setattr(sync_job, "_journal_import",
                        lambda s: calls.append("import") or {"new_submissions": 0})
    seqs = iter([(0, 0), (1, 2)])
    monkeypatch.setattr(sync_job, "_agent_seq", lambda: next(seqs))
    sync_job.main([])
    assert "push" in calls
