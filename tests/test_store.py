"""GCS persistence with generation preconditions, against an injected fake client."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from google.api_core.exceptions import PreconditionFailed
from health_data import store


class FakeBlob:
    def __init__(self, bucket: FakeBucket, name: str):
        self.bucket, self.name = bucket, name
        self.generation: int | None = None

    def download_to_filename(self, path, if_generation_match=None):
        data, gen = self.bucket.objects[self.name]
        assert if_generation_match in (None, gen)
        Path(path).write_bytes(data)

    def upload_from_filename(self, path, if_generation_match=None):
        current = self.bucket.objects.get(self.name, (b"", 0))[1]
        self.bucket.uploads.append((self.name, if_generation_match, Path(path).name))
        if if_generation_match is not None and if_generation_match != current:
            raise PreconditionFailed("generation mismatch")
        gen = self.bucket.counter = self.bucket.counter + 1
        self.bucket.objects[self.name] = (Path(path).read_bytes(), gen)
        self.generation = gen

    def upload_from_string(self, data, content_type=None):
        gen = self.bucket.counter = self.bucket.counter + 1
        self.bucket.objects[self.name] = (data.encode(), gen)

    def download_as_text(self):
        return self.bucket.objects[self.name][0].decode()


class FakeBucket:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, int]] = {}
        self.uploads: list[tuple[str, int | None, str]] = []
        self.counter = 100

    def get_blob(self, name):
        if name not in self.objects:
            return None
        blob = FakeBlob(self, name)
        blob.generation = self.objects[name][1]
        return blob

    def blob(self, name):
        return FakeBlob(self, name)


class FakeClient:
    def __init__(self):
        self.b = FakeBucket()

    def bucket(self, name):
        return self.b


def _db(path: Path, value: int = 1) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS t (v INTEGER)")
    conn.execute("INSERT INTO t VALUES (?)", (value,))
    conn.commit()
    conn.close()
    return path


def test_pull_returns_generation(tmp_path):
    client, gen_file = FakeClient(), tmp_path / ".db_generation"
    client.b.objects["health.db"] = (b"payload", 7)
    dest = tmp_path / "health.db"
    assert store.pull_db("b", "health.db", dest, client=client, gen_path=gen_file) == 7
    assert dest.read_bytes() == b"payload"
    assert gen_file.read_text().strip() == "7"


def test_pull_absent_returns_none(tmp_path):
    gen_file = tmp_path / ".db_generation"
    assert store.pull_db("b", "health.db", tmp_path / "x.db", client=FakeClient(), gen_path=gen_file) is None
    assert not gen_file.exists()


def test_push_uses_generation_precondition(tmp_path):
    client, gen_file = FakeClient(), tmp_path / ".db_generation"
    client.b.objects["health.db"] = (b"old", 5)
    src = _db(tmp_path / "local.db")
    new = store.push_db("b", "health.db", src, 5, client=client, gen_path=gen_file)
    assert client.b.uploads == [("health.db", 5, "local.db")]
    assert new == 101 and gen_file.read_text().strip() == "101"


def test_concurrent_push_raises(tmp_path):
    client = FakeClient()
    client.b.objects["health.db"] = (b"theirs", 9)  # changed after our pull at generation 5
    src = _db(tmp_path / "local.db")
    with pytest.raises(store.ConcurrentUpdateError):
        store.push_db("b", "health.db", src, 5, client=client, gen_path=tmp_path / "g")
    assert client.b.objects["health.db"] == (b"theirs", 9)


def test_first_push_creates_with_zero_precondition(tmp_path):
    client, gen_file = FakeClient(), tmp_path / "g"
    src = _db(tmp_path / "local.db")
    store.push_db("b", "health.db", src, 0, client=client, gen_path=gen_file)
    assert client.b.uploads[0][1] == 0
    assert "health.db" in client.b.objects


def test_push_checkpoints_wal_and_uploads_only_main_file(tmp_path):
    client = FakeClient()
    src = tmp_path / "local.db"
    conn = sqlite3.connect(src)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (v INTEGER)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()  # still in -wal, connection open
    store.push_db("b", "health.db", src, 0, client=client, gen_path=tmp_path / "g")
    conn.close()
    uploaded = tmp_path / "check.db"
    uploaded.write_bytes(client.b.objects["health.db"][0])
    assert sqlite3.connect(uploaded).execute("SELECT v FROM t").fetchone() == (42,)
    assert all(name == "local.db" for _, _, name in client.b.uploads)


def test_local_write_refuses_when_stale(tmp_path):
    client, gen_file = FakeClient(), tmp_path / "g"
    client.b.objects["health.db"] = (b"x", 3)
    gen_file.write_text("2")
    with pytest.raises(store.StaleLocalDbError):
        store.require_fresh("b", "health.db", client=client, gen_path=gen_file)
    gen_file.write_text("3")
    store.require_fresh("b", "health.db", client=client, gen_path=gen_file)


def test_unrecorded_local_is_stale_against_existing_remote(tmp_path):
    client, gen_file = FakeClient(), tmp_path / "g"
    store.require_fresh("b", "health.db", client=client, gen_path=gen_file)  # nothing anywhere: fine
    client.b.objects["health.db"] = (b"x", 3)
    with pytest.raises(store.StaleLocalDbError):
        store.require_fresh("b", "health.db", client=client, gen_path=gen_file)


def test_push_recorded_first_push_then_reuses_generation(tmp_path):
    client, gen_file = FakeClient(), tmp_path / "g"
    src = _db(tmp_path / "local.db")
    store.push_recorded("b", "health.db", src, client=client, gen_path=gen_file)
    store.push_recorded("b", "health.db", src, client=client, gen_path=gen_file)
    assert [u[1] for u in client.b.uploads] == [0, 101]


def test_heartbeat_round_trip_beside_the_database():
    client = FakeClient()
    assert store.read_heartbeat("bkt", "health.db", client=client) is None
    store.write_heartbeat("bkt", "health.db", {"checked_at": "t1", "ok": True}, client=client)
    assert set(client.b.objects) == {"health.db.heartbeat.json"}  # never touches the database
    assert store.read_heartbeat("bkt", "health.db", client=client) == {"checked_at": "t1", "ok": True}
