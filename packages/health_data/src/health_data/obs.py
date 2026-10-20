"""Observability: structured logging and run spans.

The standard target for agent runtimes is an OpenTelemetry span per unit of
work, with the trace tree showing the full flow. This module is the
dependency-free equivalent: a `span` context manager that records name,
duration, outcome, and arbitrary attributes as one JSON line each.

Keeping the shape span-like matters more than the transport. Emitting
`{"span": "...", "duration_ms": ..., "status": ...}` means adopting real
OTel later is a change of exporter, not a change of instrumentation.

Usage:
    log = get_logger(__name__)
    with span("ingest.data_type", data_type="steps") as s:
        s["fetched"] = 31
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime

from health_core.settings import get_settings

LOG_DIR = get_settings().data_dir / "logs"
LEVEL = os.environ.get("HEALTH_AGENT_LOG_LEVEL", "INFO").upper()
# Human-readable console by default; JSON when a collector is consuming it.
JSON_CONSOLE = os.environ.get("HEALTH_AGENT_LOG_JSON", "").lower() in ("1", "true", "yes")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "attrs", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger("health_agent")
    root.setLevel(LEVEL)
    root.propagate = False

    # The console belongs to the CLI's own output. Only problems go there by
    # default; set HEALTH_AGENT_LOG_LEVEL=INFO to follow a run live.
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(LEVEL if "HEALTH_AGENT_LOG_LEVEL" in os.environ else logging.WARNING)
    console.setFormatter(
        _JsonFormatter() if JSON_CONSOLE
        else logging.Formatter("%(levelname)-7s %(name)-18s %(message)s")
    )
    root.addHandler(console)

    # The durable trace: one JSON object per line, always, regardless of
    # what the console is doing. This is what you grep after a failed run.
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        f = logging.FileHandler(LOG_DIR / "agent.jsonl", encoding="utf-8")
        f.setFormatter(_JsonFormatter())
        root.addHandler(f)
    except OSError:
        pass  # a read-only filesystem must not take the run down
    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure()
    return logging.getLogger(f"health_agent.{name.rsplit('.', 1)[-1]}")


@contextmanager
def span(name: str, logger: logging.Logger | None = None, **attrs):
    """Time a unit of work and emit one structured record for it.

    Yields a mutable dict — assign into it to attach results that are only
    known once the work is done (row counts, page counts, cursor positions).
    Failures are recorded with the elapsed time and re-raised, never
    swallowed, so a caller's error handling is unchanged by instrumentation.
    """
    log = logger or get_logger("span")
    started = time.perf_counter()
    fields: dict = dict(attrs)
    try:
        yield fields
    except Exception as exc:
        log.error(
            f"{name} failed",
            extra={"attrs": {
                "span": name, "status": "error",
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "error_type": type(exc).__name__, **fields,
            }},
        )
        raise
    else:
        log.info(
            f"{name} ok",
            extra={"attrs": {
                "span": name, "status": "ok",
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                **fields,
            }},
        )
