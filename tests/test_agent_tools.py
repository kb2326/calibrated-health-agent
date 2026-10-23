"""The agent's capability surface: read-only, grounded, honest about n and about freshness."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest
from health_agents import tools
from health_core.settings import Settings
from health_data import civil, db, store


@pytest.fixture(autouse=True)
def empty_db(tmp_path, monkeypatch):
    """Bind tools to a throwaway schema-only DB so no real data/ is needed."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(store, "_gen_path", lambda p: tmp_path / ".db_generation")
    monkeypatch.setattr(tools, "get_settings", lambda: Settings.model_validate({"db_bucket": None}))
    db.init_db()


def test_sql_tool_refuses_every_mutation():
    for q in ("DELETE FROM journal_submissions", "UPDATE daily_metrics SET agg_value=1",
              "DROP TABLE raw_points", "INSERT INTO daily_metrics VALUES (1)",
              "PRAGMA journal_mode=DELETE", "SELECT 1; DROP TABLE raw_points"):
        assert "error" in tools.run_sql(q), f"must refuse: {q}"


def test_sql_tool_allows_reads():
    r = tools.run_sql("SELECT COUNT(*) AS c FROM daily_metrics")
    assert "error" not in r and r["n"] == 1


def test_sql_tool_allows_a_cte():
    assert "error" not in tools.run_sql("WITH t AS (SELECT 1 AS x) SELECT x FROM t")


def test_connection_itself_is_read_only():
    """Belt and braces: even past the guard, SQLite refuses the write."""
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        tools._ro_connect().execute("DELETE FROM daily_metrics")


def test_every_tool_reports_a_sample_count():
    """Grounding rule: a claim without n is not checkable."""
    for result in (tools.get_anomalies(30), tools.get_journal(30),
                   tools.get_correlations(0.3), tools.get_metric_series("steps", 30)):
        assert "n" in result


def test_definitional_pairs_are_flagged():
    corr = tools.get_correlations(0.3)["correlations"]
    pairs = {(c["metric_a"], c["metric_b"]): c["definitional"] for c in corr}
    if ("distance", "steps") in pairs:
        assert pairs[("distance", "steps")] is True


def test_learning_loop_tool_is_gone():
    assert not hasattr(tools, "get_signal_reliability")


def test_journal_reads_the_outcome_view():
    with db.connect() as conn:
        for sub, mood in (("2026-10-20T15:00:00.000000Z", 7), ("2026-10-20T16:00:00.000000Z", 3)):
            conn.execute(
                "INSERT INTO journal_submissions (date, mood, energy, soreness, note, submitted_at,"
                " source, row_hash, imported_at, status) VALUES ('2026-10-20', ?, 5, 5, 'n', ?,"
                " 'form', ?, ?, 'ok')", (mood, sub, sub, sub))
    out = tools.get_journal(3650)
    assert [e["mood"] for e in out["entries"]] == [7]  # earliest ok submission only
    assert out["as_of"]["last_journal_import"] == "2026-10-20T16:00:00.000000Z"


def test_today_follows_the_owner_zone(monkeypatch):
    # 20:00Z on the 20th is already the 21st in Asia/Kolkata
    monkeypatch.setattr(civil, "now", lambda: datetime(2026, 10, 20, 20, 0, tzinfo=UTC))
    with db.connect() as conn:
        conn.execute("INSERT INTO daily_metrics VALUES ('2026-10-20', 'steps', 100, 1)")
    out = tools.get_metric_series("steps", 1)  # since = owner today - 1 = the 20th
    assert out["n"] == 1 and out["as_of"]["today"] == "2026-10-21"
    assert out["as_of"]["timezone"] == "Asia/Kolkata"


def test_describe_substrate_reports_freshness(tmp_path):
    with db.connect() as conn:
        conn.execute("INSERT INTO sync_state VALUES ('steps', 'c', '2026-10-21T06:30:00+00:00')")
        conn.execute("INSERT INTO sync_state VALUES ('sleep', 'c', '2026-10-20T06:30:00+00:00')")
        conn.execute("INSERT INTO sync_state VALUES ('backfill:steps', 'a..b', 'x')")
    (tmp_path / ".db_generation").write_text("41")
    f = tools.describe_substrate()["freshness"]
    assert f["last_sync_by_metric"] == {"sleep": "2026-10-20T06:30:00+00:00",
                                        "steps": "2026-10-21T06:30:00+00:00"}
    assert f["newest_sync"] == "2026-10-21T06:30:00+00:00"
    assert f["recorded_generation"] == 41 and f["bucket_generation"] is None
    assert "CHA_DB_BUCKET" in f["note"]


def test_describe_substrate_compares_bucket_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "get_settings", lambda: Settings.model_validate({"db_bucket": "bkt"}))
    monkeypatch.setattr(store, "remote_generation", lambda b, o: 42)
    monkeypatch.setattr(store, "read_heartbeat", lambda b, o: None)
    (tmp_path / ".db_generation").write_text("41")
    f = tools.describe_substrate()["freshness"]
    assert (f["recorded_generation"], f["bucket_generation"], f["local_is_current"]) == (41, 42, False)


def test_describe_substrate_reports_last_bucket_check(tmp_path, monkeypatch):
    beat = {"checked_at": "2026-10-21T08:00:00.000000Z", "ok": True, "pushed": False}
    monkeypatch.setattr(tools, "get_settings", lambda: Settings.model_validate({"db_bucket": "bkt"}))
    monkeypatch.setattr(store, "remote_generation", lambda b, o: 41)
    monkeypatch.setattr(store, "read_heartbeat", lambda b, o: beat)
    assert tools.describe_substrate()["freshness"]["last_check"] == beat


def test_series_tools_carry_last_sync_time():
    with db.connect() as conn:
        conn.execute("INSERT INTO sync_state VALUES ('steps', 'c', '2026-10-21T06:30:00+00:00')")
    assert tools.get_metric_series("steps")["as_of"]["last_synced_at"] == "2026-10-21T06:30:00+00:00"
    assert tools.compare_periods("steps")["as_of"]["last_synced_at"] == "2026-10-21T06:30:00+00:00"
    assert tools.list_metrics()["as_of"]["timezone"] == "Asia/Kolkata"


def test_tools_refuse_a_newer_schema():
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.execute(f"PRAGMA user_version = {len(db.MIGRATIONS) + 1}")
    with pytest.raises(db.SchemaTooNewError):
        tools.list_metrics()
