"""Run eval cases or questions through the agent and keep one JSONL transcript per run.

A transcript holds what every grader needs: the question, final answer, each tool call with its
arguments and response, receipt ids, tokens, cost, latency, topology, ablation variant, trial,
the commit and a fingerprint of the fixture. Synthetic runs use the eval fixture in a scratch
directory; `real=True` uses the owner's database, laptop only, and must write under
`data/evals/` (git-ignored) so a real transcript can never be committed.

A model error becomes `status="not_evaluated"` with a reason (`quota` for rate limits), never a
pass or a silent skip.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from health_agents import cli, smoke
from health_agents import tools as agent_tools
from health_agents.workflow import ALL_TOOLS

from . import fixture
from .cases import Case

REAL_ROOT = Path("data/evals")
Variant = Literal["full", "no_code", "no_tools"]


@dataclass
class Transcript:
    case_id: str
    question: str
    answer: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    receipts: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    seconds: float = 0.0
    topology: str = "single"
    variant: str = "full"
    trial: int = 0
    commit: str = ""
    fixture_hash: str = ""
    status: Literal["ok", "not_evaluated"] = "ok"
    reason: str | None = None
    tags: dict = field(default_factory=dict)


def variant_tools(variant: Variant) -> list | None:
    if variant == "full":
        return None
    if variant == "no_code":
        return [t for t in ALL_TOOLS if t is not agent_tools.run_python]
    return []


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def _reason(exc: BaseException) -> str:
    text = str(exc).lower()
    if "429" in text or "resource_exhausted" in text or "quota" in text or "rate limit" in text:
        return "quota"
    return type(exc).__name__


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _items(items: Sequence[Case | dict]) -> list[tuple[str, list[str], dict]]:
    out = []
    for item in items:
        if isinstance(item, Case):
            out.append((item.id, item.turns, {"suite": item.suite, "category": item.category}))
        else:
            q = item["question"]
            out.append((item["id"], [q] if isinstance(q, str) else list(q), item.get("tags", {})))
    return out


def _run_one(case_id: str, turns: list[str], tags: dict, *, model_factory, variant: Variant,
             topology: str, trial: int, commit: str, fixture_hash: str) -> Transcript:
    t = Transcript(case_id=case_id, question=" / ".join(turns), topology=topology,
                   variant=variant, trial=trial, commit=commit, fixture_hash=fixture_hash, tags=tags)
    start = time.monotonic()
    try:
        session = cli.Session(model=model_factory() if model_factory else None,
                              refresh_memory=False, tools=variant_tools(variant),
                              topology=topology)  # type: ignore[arg-type]
        for turn in turns:
            result = session.ask(turn, confirm=lambda _args: False)
            t.answer = result.answer
            t.tool_calls += _jsonable(result.tool_calls)
            t.receipts += [r for r in result.receipts if r not in t.receipts]
            t.input_tokens += result.input_tokens
            t.output_tokens += result.output_tokens
            t.usd += result.usd
    except Exception as exc:  # the run is not graded; the reason is kept
        t.status, t.reason = "not_evaluated", _reason(exc)
    t.seconds = round(time.monotonic() - start, 3)
    return t


def collect(items: Sequence[Case | dict], *, topology: str = "single", trials: int = 1,
            variant: Variant = "full", model_factory: Callable[[], Any] | None = None,
            commit: str = "", fixture_hash: str = "", pace_s: float = 0) -> list[Transcript]:
    """Run every item `trials` times against whatever database is active (no fixture setup).

    `pace_s` waits between runs so a rate-limited key (free tier: 15 requests a minute)
    is not exhausted by a burst; a quota error would make the run not evaluated."""
    out: list[Transcript] = []
    for case_id, turns, tags in _items(items):
        for trial in range(trials):
            if out and pace_s:
                time.sleep(pace_s)
            out.append(_run_one(case_id, turns, tags, model_factory=model_factory,
                                variant=variant, topology=topology, trial=trial, commit=commit,
                                fixture_hash=fixture_hash))
    return out


def write(transcripts: list[Transcript], out: Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        for t in transcripts:
            fh.write(json.dumps(asdict(t), ensure_ascii=False) + "\n")
    return out


@contextmanager
def eval_fixture(workdir: Path | None = None) -> Iterator[tuple[Path, str]]:
    """Build the eval fixture in `workdir` (or a temp dir) and point the agent at it."""
    work = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="cha-eval-"))
    work.mkdir(parents=True, exist_ok=True)
    path = fixture.build(work / "health.db")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    with smoke.use_fixture(work, path):
        yield path, digest


def run(items: Sequence[Case | dict], *, topology: str = "single", trials: int = 1,
        variant: Variant = "full", model_factory: Callable[[], Any] | None = None,
        real: bool = False, out: Path, workdir: Path | None = None) -> list[Transcript]:
    out = Path(out)
    if real and os.environ.get("CHA_DATA_MODE") == "synthetic":
        raise ValueError("CHA_DATA_MODE=synthetic (CI, free-tier key): real-data runs are refused")
    if real and not out.resolve().is_relative_to(REAL_ROOT.resolve()):
        raise ValueError("real-data transcripts must be written under data/evals/")
    kw = {"topology": topology, "trials": trials, "variant": variant,
          "model_factory": model_factory, "commit": _commit()}
    if real:
        transcripts = collect(items, fixture_hash="real", **kw)
    else:
        with eval_fixture(workdir) as (_, digest):
            transcripts = collect(items, fixture_hash=digest, **kw)
    write(transcripts, out)
    return transcripts


def load(path: Path) -> list[Transcript]:
    return [Transcript(**json.loads(line)) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]
