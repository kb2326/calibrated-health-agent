"""One shared agent.db in the bucket for the CLI and the web (Phase 5 Task 4)."""
from __future__ import annotations

import sqlite3

import pytest
from health_agents import agent_db, agent_db_sync, costs
from test_store import FakeClient


def _rows(path, table="chat_usage") -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _local():
    with agent_db.connect():  # creates the schema
        pass
    return agent_db.get_settings().agent_db_path


def test_seed_then_pull_then_push_round_trip(tmp_path):
    client = FakeClient()
    path = _local()
    costs.record_chat(100, 20)
    assert agent_db_sync.seed("b", "agent.db", path, client=client) == "seeded"
    gen = agent_db_sync.pull_agent_db("b", "agent.db", path, client=client)
    assert gen is not None
    since = agent_db_sync.snapshot_rowids(path)
    costs.record_chat(100, 20)
    assert agent_db_sync.push_agent_db("b", "agent.db", path, since=since, client=client) == "pushed"
    assert client.b.objects["agent.db"][1] > gen


def test_seed_refuses_when_object_exists(tmp_path):
    client = FakeClient()
    path = _local()
    agent_db_sync.seed("b", "agent.db", path, client=client)
    assert agent_db_sync.seed("b", "agent.db", path, client=client) == "exists"


def test_push_race_reappends_once_then_reports(tmp_path, monkeypatch):
    client = FakeClient()
    path = _local()
    agent_db_sync.seed("b", "agent.db", path, client=client)
    agent_db_sync.pull_agent_db("b", "agent.db", path, client=client)
    since = agent_db_sync.snapshot_rowids(path)
    costs.record_chat(100, 20)  # this turn's row

    # another writer (the phone) pushes first: one extra row in the bucket copy
    other = tmp_path / "other.db"
    other.write_bytes(client.b.objects["agent.db"][0])
    conn = sqlite3.connect(other)
    conn.execute("INSERT INTO chat_usage (month, input_tokens, output_tokens, usd, created_at)"
                 " VALUES ('2026-10', 1, 1, 0.001, 'x')")
    conn.commit()
    conn.close()
    data, gen = client.b.objects["agent.db"]
    client.b.objects["agent.db"] = (other.read_bytes(), gen + 1)

    assert agent_db_sync.push_agent_db("b", "agent.db", path, since=since, client=client) == "reappended"
    final = tmp_path / "final.db"
    final.write_bytes(client.b.objects["agent.db"][0])
    assert _rows(final) == 2  # both writers' rows

    # two conflicts in a row: report, never loop
    since = agent_db_sync.snapshot_rowids(path)
    costs.record_chat(5, 5)
    real_pull = agent_db_sync.pull_agent_db

    def pull_then_bump(*a, **k):
        g = real_pull(*a, **k)
        d, cur = client.b.objects["agent.db"]
        client.b.objects["agent.db"] = (d, cur + 1)
        return g

    d, cur = client.b.objects["agent.db"]
    client.b.objects["agent.db"] = (d, cur + 1)
    monkeypatch.setattr(agent_db_sync, "pull_agent_db", pull_then_bump)
    assert agent_db_sync.push_agent_db("b", "agent.db", path, since=since, client=client) == "not_saved"


def test_generation_file_is_separate_from_health_db(tmp_path):
    """health.db's generation and content-hash records must not be touched."""
    client = FakeClient()
    path = _local()
    agent_db_sync.seed("b", "agent.db", path, client=client)
    agent_db_sync.pull_agent_db("b", "agent.db", path, client=client)
    from health_core.settings import get_settings

    assert not (get_settings().data_dir / ".db_generation").exists()
    assert not (get_settings().data_dir / ".db_content_sha256").exists()


@pytest.fixture(autouse=True)
def _settings(tmp_path, monkeypatch):
    from health_core import settings as settings_mod
    from health_core.settings import Settings

    s = Settings.model_validate({"data_dir": tmp_path})
    monkeypatch.setattr(agent_db, "get_settings", lambda: s)
    monkeypatch.setattr(settings_mod, "get_settings", lambda: s)
    monkeypatch.setattr(agent_db_sync, "get_settings", lambda: s, raising=False)


def test_cli_turn_pulls_and_pushes_when_bucket_set(tmp_path, monkeypatch):
    from agent_fakes import FakeLlm, text
    from health_agents import cli
    from health_core.settings import Settings

    client = FakeClient()
    s = Settings.model_validate({"data_dir": tmp_path, "db_bucket": "b"})
    monkeypatch.setattr(agent_db, "get_settings", lambda: s)
    monkeypatch.setattr(agent_db_sync, "get_settings", lambda: s)
    monkeypatch.setattr(cli, "get_settings", lambda: s)
    real_pull, real_push = agent_db_sync.pull_agent_db, agent_db_sync.push_agent_db
    monkeypatch.setattr(agent_db_sync, "pull_agent_db",
                        lambda b, o, d, client=None: real_pull(b, o, d, client=client_))
    monkeypatch.setattr(agent_db_sync, "push_agent_db",
                        lambda b, o, sp, since, client=None: real_push(b, o, sp, since=since, client=client_))
    client_ = client
    session = cli.Session(model=FakeLlm([text("Hello.")]), refresh_memory=False)
    result = session.ask("Hi")
    assert result.saved == "pushed"
    assert "agent.db" in client.b.objects  # first push creates the shared copy
