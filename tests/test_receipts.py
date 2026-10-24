"""Receipts: content-addressed records of the code behind every number."""
from __future__ import annotations

from typing import Any

import pytest
from health_agents import agent_db, receipts
from health_core.settings import Settings
from health_data import db
from ledger_fixtures import make_db


@pytest.fixture
def dbs(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_db, "get_settings", lambda: Settings.model_validate({"data_dir": tmp_path}))
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "health.db")
    make_db(tmp_path / "health.db").close()
    return tmp_path


def _rec(conn, **over):
    kw: dict[str, Any] = dict(kind="sql", code="SELECT 1", data_hash="h", as_of="2026-10-22", output=[{"x": 1}],
              executor=receipts.SQLITE, context="chat")
    kw.update(over)
    return receipts.record(conn, **kw)


def test_same_content_same_id_and_one_row(dbs):
    with agent_db.connect() as conn:
        a, b = _rec(conn), _rec(conn)
        assert a == b and a.startswith("r-") and len(a) == 12
        assert conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 1
        assert _rec(conn, output=[{"x": 2}]) != a


def test_get_finds_chat_then_investigator_receipts(dbs):
    with agent_db.connect() as conn:
        chat_id = _rec(conn)
    with db.connect() as conn:
        inv_id = _rec(conn, code="SELECT 2", context="investigator")
    got, where = receipts.get(chat_id) or (None, None)
    assert got is not None and got.code == "SELECT 1" and where == "chat"
    got, where = receipts.get(inv_id) or (None, None)
    assert got is not None and got.context == "investigator" and where == "investigator"
    assert receipts.get("r-nope") is None


def test_output_round_trips_as_json(dbs):
    with agent_db.connect() as conn:
        rid = _rec(conn, output={"result": 6.4, "n": 12})
    found = receipts.get(rid)
    assert found is not None and found[0].output == {"result": 6.4, "n": 12}
