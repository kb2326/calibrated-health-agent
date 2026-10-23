"""Publishing the chain: private retention bucket mirror and the public date+hash log."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from google.api_core.exceptions import PreconditionFailed
from health_ledger import chain, publish, scoreboard
from ledger_fixtures import make_db


class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket, self.name = bucket, name

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        assert if_generation_match == 0
        if self.name in self.bucket.objects:
            raise PreconditionFailed("exists")
        self.bucket.objects[self.name] = data


class FakeBucket:
    def __init__(self, existing=()):
        self.objects = dict.fromkeys(existing, "old")

    def blob(self, name):
        return FakeBlob(self, name)

    def list_blobs(self, prefix=""):
        return [type("B", (), {"name": n})() for n in self.objects if n.startswith(prefix)]


class FakeStorage:
    def __init__(self, bucket):
        self.b = bucket

    def bucket(self, name):
        return self.b


@pytest.fixture
def conn(tmp_path):
    c = make_db(tmp_path / "t.db")
    chain.ensure_plan_hash(c, "ab")
    chain.append(c, "2026-10-30", "lock", {"snapshot_hash": "s"})
    chain.append(c, "2026-10-30", "outcome", {"x": 1})
    chain.append(c, "2026-10-31", "lock", {"snapshot_hash": "t"})  # not settled yet
    c.commit()
    yield c
    c.close()


def test_bucket_mirror_never_overwrites(conn):
    bucket = FakeBucket(existing=["ledger/000001-0000-00-00-plan.json"])
    assert publish.to_bucket(conn, "b", client=FakeStorage(bucket)) == 3
    assert bucket.objects["ledger/000001-0000-00-00-plan.json"] == "old"
    body = json.loads(bucket.objects["ledger/000003-2026-10-30-outcome.json"])
    assert body["seq"] == 3 and body["kind"] == "outcome" and len(body["entry_hash"]) == 64
    assert publish.to_bucket(conn, "b", client=FakeStorage(bucket)) == 0


def test_bucket_race_counts_as_published(conn):
    class RacyBucket(FakeBucket):
        def list_blobs(self, prefix=""):
            return []  # listed before another run uploaded

    bucket = RacyBucket(existing=["ledger/000001-0000-00-00-plan.json"])
    assert publish.to_bucket(conn, "b", client=FakeStorage(bucket)) == 3


class FakeGit:
    """Records git calls; a clone materialises `files` in the target directory."""

    def __init__(self, files: dict[str, str] | None = None):
        self.files, self.calls = files or {}, []
        self.key_seen: Path | None = None
        self.committed: dict[str, str] = {}

    def __call__(self, args: list[str], *, cwd: Path | None = None, env: dict | None = None):
        self.calls.append(args)
        if args[0] == "clone":
            target = Path(args[-1])
            target.mkdir(parents=True)
            for name, text in self.files.items():
                (target / name).parent.mkdir(parents=True, exist_ok=True)
                (target / name).write_text(text)
            assert env is not None
            match = re.search(r"-i (\S+)", env["GIT_SSH_COMMAND"])
            assert match is not None
            self.key_seen = Path(match.group(1))
            assert self.key_seen.read_text() == "PRIVATE\n"  # ssh needs the final newline
        if "commit" in args:
            assert cwd is not None
            self.committed = {p.relative_to(cwd).as_posix(): p.read_text()
                              for p in cwd.rglob("*") if p.is_file()}


@pytest.fixture
def board(conn):
    return scoreboard.build(conn)


def test_repo_publishes_date_and_hash_only(conn, board):
    git = FakeGit()
    assert publish.to_repo(conn, "git@github.com:kb2326/cha-ledger-log.git", "PRIVATE", board, git=git) == 2
    lines = git.committed["docs/chain.csv"].splitlines()
    assert lines[0] == "date,chain_hash"
    assert all(re.fullmatch(r"(plan|\d{4}-\d\d-\d\d),[0-9a-f]{64}", line) for line in lines[1:])
    assert [line.split(",")[0] for line in lines[1:]] == ["plan", "2026-10-30"]  # 10-31 unsettled
    outcome_hash = conn.execute("SELECT entry_hash FROM ledger WHERE kind='outcome'").fetchone()[0]
    assert lines[2].endswith(outcome_hash)
    assert json.loads(git.committed["docs/scoreboard.json"]) == publish.public_board(board)
    assert "<html" in git.committed["docs/index.html"]
    assert ["push", "origin", "HEAD"] in git.calls


def test_repo_skips_dates_already_in_chain_csv(conn, board):
    plan_hash = conn.execute("SELECT entry_hash FROM ledger WHERE kind='plan'").fetchone()[0]
    git = FakeGit({"docs/chain.csv": f"date,chain_hash\nplan,{plan_hash}\n"})
    assert publish.to_repo(conn, "u", "PRIVATE", board, git=git) == 1
    assert git.committed["docs/chain.csv"].count("plan,") == 1


def test_repo_noop_when_nothing_new(conn, board):
    rows = conn.execute("SELECT entry_hash FROM ledger WHERE kind IN ('plan','outcome') ORDER BY seq").fetchall()
    csv = f"date,chain_hash\nplan,{rows[0][0]}\n2026-10-30,{rows[1][0]}\n"
    git = FakeGit({"docs/chain.csv": csv,
                   "docs/scoreboard.json": json.dumps(publish.public_board(board))})
    assert publish.to_repo(conn, "u", "PRIVATE", board, git=git) == 0
    assert not any("commit" in c or "push" in c for c in git.calls)


def test_key_file_removed_after_push(conn, board):
    git = FakeGit()
    publish.to_repo(conn, "u", "PRIVATE", board, git=git)
    assert git.key_seen is not None and not git.key_seen.exists()


def _settled(board: dict) -> int:
    return board["days_scored"] + board["days_voided"] + board["days_no_outcome"]


def test_board_not_republished_one_settlement_apart(conn, board):
    # Differencing two public boards one settled day apart would reveal that day's score.
    old = {**board, "days_scored": 0, "days_voided": 0, "days_no_outcome": 0}
    assert publish.board_due(old, {**old, "days_scored": 1}) is False
    assert publish.board_due(old, {**old, "days_scored": publish.BOARD_EVERY - 1}) is False
    assert publish.board_due(old, {**old, "days_scored": publish.BOARD_EVERY}) is True
    assert publish.board_due(None, old) is True


def test_public_board_is_rounded(conn, board):
    board = {**board, "forecasters": [{"id": "a", "target": "energy", "n": 3,
                                       "mean_rps": 0.123456789,
                                       "skill_vs_climatology": {"skill": 0.98765, "n": 3},
                                       "skill_vs_persistence": None}]}
    row = publish.public_board(board)["forecasters"][0]
    assert row["mean_rps"] == 0.12 and row["skill_vs_climatology"]["skill"] == 0.99


def test_repo_keeps_old_board_until_seven_more_days_settle(conn, board):
    published = publish.public_board({**board, "days_scored": 0})
    git = FakeGit({"docs/scoreboard.json": json.dumps(published)})
    publish.to_repo(conn, "u", "PRIVATE", {**board, "days_scored": 1}, git=git)
    assert json.loads(git.committed["docs/scoreboard.json"]) == published  # chain line only


def test_repo_refuses_a_published_hash_that_differs(conn, board):
    git = FakeGit({"docs/chain.csv": "date,chain_hash\nplan," + "f" * 64 + "\n"})
    with pytest.raises(publish.LedgerMismatch, match="plan"):
        publish.to_repo(conn, "u", "PRIVATE", board, git=git)


def test_bucket_refuses_a_mirrored_hash_that_differs(conn):
    class Tagged(FakeBucket):
        def list_blobs(self, prefix=""):
            return [type("B", (), {"name": "ledger/000001-0000-00-00-plan.json",
                                   "metadata": {"entry_hash": "f" * 64}})()]

    with pytest.raises(publish.LedgerMismatch, match="seq 1"):
        publish.to_bucket(conn, "b", client=FakeStorage(Tagged()))
