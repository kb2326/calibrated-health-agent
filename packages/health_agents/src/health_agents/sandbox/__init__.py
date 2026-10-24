"""Run model-written Python over handed-in data, in a fresh locked-down child process.

Layers (spec §4.2): a static policy check (`policy.check`), a child started with `-s -P` (no user site, no script directory) in an
empty temp directory with a scrubbed environment (no credentials, no project settings),
an audit hook in the child that blocks network, processes, ctypes and file writes,
resource limits on Linux (CPU, address space, file size, process count), a wall-clock
timeout and an output cap. The child never opens the database: data arrives as JSON.

Defense in depth, not a VM boundary. In the cloud job Cloud Run's gVisor sits underneath.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import policy

RUNNER = Path(__file__).with_name("runner.py")
CPU_SECONDS = 10
ADDRESS_SPACE = 1536 * 1024 * 1024  # numpy/pandas need ~0.5 GiB of address space to import
_KEEP_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG")


@dataclass(frozen=True)
class SandboxResult:
    ok: bool
    result: Any
    stdout: str
    error: str | None
    seconds: float


def _child_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in _KEEP_ENV if k in os.environ}
    env.update(PYTHONHASHSEED="0", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
               MKL_NUM_THREADS="1")
    return env


def _limits() -> None:  # runs in the child between fork and exec (Linux only)
    if sys.platform == "win32":
        return
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (ADDRESS_SPACE, ADDRESS_SPACE))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))


def run(code: str, bundle: dict, *, timeout_s: float = 15.0) -> SandboxResult:
    start = time.monotonic()

    def done(ok: bool, result: Any = None, stdout: str = "", error: str | None = None):
        return SandboxResult(ok, result, stdout, error, round(time.monotonic() - start, 3))

    refusal = policy.check(code)
    if refusal:
        return done(False, error=refusal)
    payload = json.dumps({"code": code, "bundle": bundle})
    with tempfile.TemporaryDirectory(prefix="cha-sandbox-") as cwd:
        try:
            proc = subprocess.run(
                # Not -I: it would also ignore PYTHONHASHSEED, and receipts need set order
                # to repeat. The environment is ours alone (_child_env), so -E adds nothing.
                [sys.executable, "-s", "-P", "-X", "utf8", str(RUNNER)], input=payload,
                capture_output=True, text=True, encoding="utf-8", cwd=cwd, env=_child_env(),
                timeout=timeout_s, preexec_fn=_limits if sys.platform.startswith("linux") else None)
        except subprocess.TimeoutExpired:
            return done(False, error=f"timeout after {timeout_s:g}s")
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        return done(False, error=f"sandbox exited with code {proc.returncode} and no result")
    try:
        out = json.loads(lines[-1])
    except ValueError:
        return done(False, error="sandbox returned malformed output")
    if out.get("ok"):
        return done(True, out.get("result"), out.get("stdout", ""))
    return done(False, stdout=out.get("stdout", ""), error=out.get("error"))
