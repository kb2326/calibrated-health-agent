"""run_sql behind SQLite's own authorizer: reads of allowed tables only, a time limit, receipts."""
from __future__ import annotations

import pytest
from health_agents import receipts, sqlguard, tools
from health_core.settings import Settings
from health_data import db, store


@pytest.fixture(autouse=True)
def empty_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(store, "_gen_path", lambda p: tmp_path / ".db_generation")
    monkeypatch.setattr(tools, "get_settings", lambda: Settings.model_validate({"db_bucket": None}))
    db.init_db()
    with db.connect() as conn:
        conn.execute("INSERT INTO daily_metrics (date, data_type, agg_value, n_points, source) "
                     "VALUES ('2026-10-20', 'heart-rate', 61, 1, '')")


def test_replace_function_is_allowed():
    r = tools.run_sql("SELECT replace(data_type, '-', '_') AS t FROM daily_metrics")
    assert "error" not in r and r["rows"] == [{"t": "heart_rate"}]


@pytest.mark.parametrize("table", sorted(sqlguard.BLINDED))
def test_blinded_tables_refused_by_authorizer(table):
    r = tools.run_sql(f"SELECT * FROM {table}")
    assert "error" in r and r["rows"] == []


def test_blinded_table_in_subquery_or_join_refused():
    for q in ("SELECT * FROM daily_metrics WHERE date IN (SELECT day FROM scores)",
              "SELECT d.date FROM daily_metrics d JOIN forecasts f ON f.day = d.date"):
        assert "blinded" in tools.run_sql(q)["error"]


def test_pragma_refused():
    assert "error" in tools.run_sql("PRAGMA table_info(daily_metrics)")
    assert "error" in tools.run_sql("SELECT * FROM pragma_table_info('daily_metrics')")


def test_attach_refused():
    assert "error" in tools.run_sql("ATTACH DATABASE 'x.db' AS x")


def test_load_extension_refused():
    assert "error" in tools.run_sql("SELECT load_extension('x')")


def test_slow_query_is_interrupted(monkeypatch):
    monkeypatch.setattr(sqlguard, "TIME_LIMIT_S", 0.5)
    r = tools.run_sql("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c "
                      "WHERE x < 1000000000) SELECT COUNT(*) FROM c")
    assert "interrupted" in r["error"]


def test_multiple_statements_refused():
    assert "error" in tools.run_sql("SELECT 1; SELECT 2")


def test_window_and_date_functions_allowed():
    r = tools.run_sql("SELECT date, lag(agg_value) OVER (ORDER BY date) AS p, "
                      "strftime('%w', date) AS w FROM daily_metrics")
    assert "error" not in r


def test_run_sql_returns_a_receipt_id():
    r = tools.run_sql("SELECT 1 AS x")
    assert r["receipt"].startswith("r-")
    found = receipts.get(r["receipt"])
    assert found is not None and found[0].kind == "sql"


def test_run_python_returns_result_and_receipt():
    r = tools.run_python("result = int(metrics.value.sum())")
    assert r["result"] == 61 and r["receipt"].startswith("r-")


def test_run_python_error_is_reported():
    r = tools.run_python("import os")
    assert "error" in r and "receipt" not in r


def test_rerun_matches_on_same_data():
    rid = tools.run_python("result = int(metrics.value.sum())")["receipt"]
    out = receipts.rerun(rid)
    assert out["matches"] and not out["data_changed"] and out["new"] == 61


def test_rerun_reports_changed_data():
    rid = tools.run_python("result = int(metrics.value.sum())")["receipt"]
    sql_rid = tools.run_sql("SELECT SUM(agg_value) AS s FROM daily_metrics")["receipt"]
    with db.connect() as conn:
        conn.execute("INSERT INTO daily_metrics (date, data_type, agg_value, n_points, source) "
                     "VALUES ('2026-10-19', 'heart-rate', 9, 1, '')")
    out = receipts.rerun(rid)
    assert not out["matches"] and out["data_changed"] and (out["old"], out["new"]) == (61, 70)
    sql_out = receipts.rerun(sql_rid)
    assert not sql_out["matches"] and sql_out["data_changed"]


def test_journal_outcome_view_is_readable():
    r = tools.run_sql("SELECT COUNT(*) AS n FROM journal_outcome")
    assert "error" not in r, r


def test_cte_named_like_nothing_real_reads_fine():
    r = tools.run_sql("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c "
                      "WHERE x < 5) SELECT SUM(x) AS s FROM c")
    assert r["rows"] == [{"s": 15}]
