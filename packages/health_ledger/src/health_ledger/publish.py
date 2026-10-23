"""Publish the chain where it cannot be quietly rewritten.

Two destinations, both append-only from here, and both checked rather than remembered
(publishing never writes to the database):

- `to_bucket`: every ledger row as one JSON object in the private ledger bucket
  (`ledger/<seq:06d>-<day>-<kind>.json`, tagged with its entry hash), uploaded with
  `if_generation_match=0` so an existing object is never overwritten. The bucket's
  retention policy blocks deletes.
- `to_repo`: the public repo gets `docs/chain.csv` (`date,chain_hash`: one line for the
  plan, then one per settled day carrying that day's settlement entry hash) plus the
  aggregate scoreboard (`docs/scoreboard.json`, `docs/index.html`) for GitHub Pages. It
  pushes over SSH with a deploy key that can write to that one repo only; the key file
  exists only inside a temporary directory for the duration of the push, and GitHub's
  host key is pinned.

Privacy: the public git history keeps every version of the scoreboard, so two versions
one settled day apart would let anyone difference out that day's score (and from the
simple forecasters' scores, the day's ratings). The public board is therefore rounded to
2 decimals and republished only after `BOARD_EVERY` more days have settled, so any
difference covers at least a week. Nothing about a single day other than its date and
chain hash is published.

Integrity: if a destination already holds a different hash for an entry or a date, the
database and the public record have diverged; that raises `LedgerMismatch` (and fails
the run) instead of being skipped.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from health_ledger import scoreboard

SETTLED = ("outcome", "void", "no_outcome")
# GitHub's published SSH host key (docs.github.com, "GitHub's SSH key fingerprints").
GITHUB_HOST_KEY = ("github.com ssh-ed25519 "
                   "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl")
BOT = ("cha-ledger-bot", "noreply@users.noreply.github.com")
CSV_HEADER = "date,chain_hash"
BOARD_EVERY = 7  # settled days between two public scoreboard versions
DECIMALS = 2

Git = Callable[..., None]


class LedgerMismatch(RuntimeError):
    """A destination holds a different hash than the database for the same entry."""


def _storage(client: Any) -> Any:
    if client is not None:
        return client
    from google.cloud import storage
    from health_core.settings import get_settings

    return storage.Client(project=get_settings().gcp_project)


def to_bucket(conn: sqlite3.Connection, bucket: str, *, client: Any = None) -> int:
    from google.api_core.exceptions import PreconditionFailed

    b = _storage(client).bucket(bucket)
    existing = {blob.name: (getattr(blob, "metadata", None) or {}).get("entry_hash")
                for blob in b.list_blobs(prefix="ledger/")}
    uploaded = 0
    cols = ("seq", "day", "kind", "payload_json", "payload_hash", "prev_hash", "entry_hash",
            "created_at")
    for row in conn.execute(f"SELECT {', '.join(cols)} FROM ledger ORDER BY seq"):
        entry = dict(zip(cols, row, strict=True))
        name = f"ledger/{entry['seq']:06d}-{entry['day']}-{entry['kind']}.json"
        if name in existing:
            tagged = existing[name]
            if tagged is not None and tagged != entry["entry_hash"]:
                raise LedgerMismatch(f"seq {entry['seq']}: bucket holds a different entry hash")
            continue
        blob = b.blob(name)
        blob.metadata = {"entry_hash": entry["entry_hash"]}
        try:
            blob.upload_from_string(json.dumps(entry, sort_keys=True),
                                    content_type="application/json", if_generation_match=0)
            uploaded += 1
        except PreconditionFailed:  # another run uploaded it after our listing
            pass
    return uploaded


def chain_lines(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """(date, hash) for the plan and every settled day, in chain order."""
    rows = conn.execute(
        f"""SELECT CASE kind WHEN 'plan' THEN 'plan' ELSE day END, entry_hash FROM ledger
            WHERE kind = 'plan' OR kind IN ({",".join("?" * len(SETTLED))}) ORDER BY seq""",
        SETTLED)
    return [(d, h) for d, h in rows]


def _round(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, DECIMALS)
    if isinstance(value, dict):
        return {k: _round(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round(v) for v in value]
    return value


def public_board(board: dict) -> dict:
    """The scoreboard as published: every float rounded to 2 decimals."""
    return _round(board)


def _settled(board: dict) -> int:
    return board["days_scored"] + board["days_voided"] + board["days_no_outcome"]


def board_due(published: dict | None, board: dict) -> bool:
    """Republish only when at least BOARD_EVERY more days have settled (or none is out)."""
    return published is None or _settled(board) >= _settled(published) + BOARD_EVERY


def run_git(args: list[str], *, cwd: Path | None = None, env: dict | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)


def to_repo(conn: sqlite3.Connection, repo_url: str, key_pem: str, board: dict, *,
            git: Git = run_git) -> int:
    """Push new chain lines (and the scoreboard when due); returns the number of new lines."""
    with tempfile.TemporaryDirectory(prefix="cha-ledger-") as tmp:
        tmpdir = Path(tmp)
        key, hosts, work = tmpdir / "key", tmpdir / "known_hosts", tmpdir / "repo"
        key.write_text(key_pem if key_pem.endswith("\n") else key_pem + "\n")
        key.chmod(0o600)
        hosts.write_text(GITHUB_HOST_KEY + "\n")
        env = {**os.environ, "GIT_SSH_COMMAND": (
            f"ssh -i {key} -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "
            f"-o UserKnownHostsFile={hosts}")}
        git(["clone", "--depth", "1", repo_url, str(work)], env=env)
        docs = work / "docs"
        docs.mkdir(exist_ok=True)
        csv, board_path = docs / "chain.csv", docs / "scoreboard.json"
        lines = csv.read_text().splitlines() if csv.exists() else [CSV_HEADER]
        published = dict(line.split(",", 1) for line in lines[1:] if "," in line)
        new = []
        for day, entry_hash in chain_lines(conn):
            if day not in published:
                new.append(f"{day},{entry_hash}")
            elif published[day] != entry_hash:
                raise LedgerMismatch(f"{day}: public chain.csv holds a different hash")
        old_board = json.loads(board_path.read_text()) if board_path.exists() else None
        write_board = board_due(old_board, board)
        if not new and not write_board:
            return 0
        csv.write_text("\n".join(lines + new) + "\n")
        if write_board:
            out = public_board(board)
            board_path.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
            (docs / "index.html").write_text(scoreboard.render_html(out))
        git(["add", "docs"], cwd=work, env=env)
        git(["-c", f"user.name={BOT[0]}", "-c", f"user.email={BOT[1]}", "commit", "-m",
             f"ledger: {len(new)} new chain line(s)"
             + (", scoreboard refresh" if write_board else "")], cwd=work, env=env)
        git(["push", "origin", "HEAD"], cwd=work, env=env)
        return len(new)
