"""Safer push/pull: missing source, busy checkpoint, failed download."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from health_data import store
from test_store import FakeBlob, FakeClient, _db


def test_push_refuses_missing_source_and_creates_nothing(tmp_path):
    client = FakeClient()
    with pytest.raises(FileNotFoundError):
        store.push_db("b", "health.db", tmp_path / "none.db", 0, client=client, gen_path=tmp_path / "g")
    assert not (tmp_path / "none.db").exists() and client.b.uploads == []


def test_push_refuses_when_checkpoint_busy(tmp_path):
    client = FakeClient()
    src = _db(tmp_path / "local.db")
    reader = sqlite3.connect(src)
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM t").fetchall()  # open read txn blocks TRUNCATE
    writer = sqlite3.connect(src)
    writer.execute("INSERT INTO t VALUES (9)")
    writer.commit()
    try:
        with pytest.raises(RuntimeError, match="busy"):
            store.push_db("b", "health.db", src, 0, client=client, gen_path=tmp_path / "g")
    finally:
        reader.close()
        writer.close()
    assert client.b.uploads == []


def test_pull_failure_removes_part_file(tmp_path, monkeypatch):
    client = FakeClient()
    client.b.objects["health.db"] = (b"x", 3)

    def boom(self, path, if_generation_match=None):
        Path(path).write_bytes(b"partial")
        raise OSError("network")

    monkeypatch.setattr(FakeBlob, "download_to_filename", boom)
    with pytest.raises(OSError):
        store.pull_db("b", "health.db", tmp_path / "health.db", client=client, gen_path=tmp_path / "g")
    assert not (tmp_path / "health.db.part").exists() and not (tmp_path / "health.db").exists()
