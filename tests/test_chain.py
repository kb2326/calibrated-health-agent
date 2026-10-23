"""The hash chain: every ledger entry commits to everything before it."""
from __future__ import annotations

import sqlite3

import pytest
from health_ledger import chain, features
from ledger_fixtures import make_db


@pytest.fixture
def conn(tmp_path):
    c = make_db(tmp_path / "t.db")
    yield c
    c.close()


def test_chain_links_prev_hash(conn):
    first = chain.append(conn, "0000-00-00", "plan", {"analysis_plan_sha256": "ab"})
    second = chain.append(conn, "2026-10-30", "lock", {"snapshot_hash": "x"})
    rows = conn.execute("SELECT prev_hash, entry_hash, payload_hash FROM ledger ORDER BY seq").fetchall()
    assert rows[0][0] == chain.GENESIS_PREV and rows[0][1] == first
    assert rows[1][0] == first and rows[1][1] == second
    assert rows[1][2] == features.sha256(features.canonical({"snapshot_hash": "x"}))
    assert second == features.sha256(f"{first}|2026-10-30|lock|{rows[1][2]}")
    assert chain.verify(conn) == []


def test_chain_verify_detects_edited_payload(conn):
    chain.ensure_plan_hash(conn, "ab")
    chain.append(conn, "2026-10-30", "lock", {"snapshot_hash": "x"})
    conn.commit()
    conn.execute("DROP TRIGGER ledger_no_update")  # simulate tampering with the raw file
    conn.execute("UPDATE ledger SET payload_json = '{\"snapshot_hash\":\"y\"}' WHERE kind = 'lock'")
    problems = chain.verify(conn)
    assert problems and "seq 2" in problems[0]


def test_chain_verify_requires_plan_first(conn):
    chain.append(conn, "2026-10-30", "lock", {"snapshot_hash": "x"})
    assert chain.verify(conn) == ["seq 1: the first entry must be the analysis plan"]


def test_ensure_plan_is_idempotent(conn, tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_bytes(b"# plan\n")
    chain.ensure_plan(conn, plan)
    chain.ensure_plan(conn, plan)
    rows = conn.execute("SELECT day, kind, payload_json FROM ledger").fetchall()
    assert rows == [("0000-00-00", "plan",
                     features.canonical({"analysis_plan_sha256": features.sha256("# plan\n")}))]


def test_ledger_rows_cannot_be_edited_through_sqlite(conn):
    chain.ensure_plan_hash(conn, "ab")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM ledger")


def test_plan_hash_ignores_line_endings(tmp_path):
    lf, crlf = tmp_path / "lf.md", tmp_path / "crlf.md"
    lf.write_bytes(b"# plan\nline\n")
    crlf.write_bytes(b"# plan\r\nline\r\n")
    assert chain.plan_sha256(lf) == chain.plan_sha256(crlf) == features.sha256("# plan\nline\n")
