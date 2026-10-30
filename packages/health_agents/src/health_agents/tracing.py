"""OpenTelemetry tracing through ADK's own instrumentation, with message content off.

`CHA_TRACING` picks the backend (default `off`):

- `local`: OTLP over HTTP to Phoenix on the laptop (`docker run -p 6006:6006
  arizephoenix/phoenix`, then http://localhost:6006). `CHA_TRACE_CONTENT=1` additionally
  records prompts and replies, and only here: the data never leaves the machine.
- `cloud`: Cloud Trace via ADK's GCP exporter, used by the Cloud Run job. Content capture is
  forced off whatever the environment says: health data must not land in a trace store.

Both ADK content knobs are set explicitly every time, because ADK's legacy span content
defaults to on. Tool spans gain `cha.receipt_id` and `cha.args_sha` (a hash, never the
arguments); each chat turn gets a `cha.turn` span with its cost (`cha.usd`).
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Literal

Mode = Literal["off", "local", "cloud"]
MODES = ("off", "local", "cloud")
PHOENIX = "http://localhost:6006/v1/traces"
SERVICE = "calibrated-health-agent"
_ADK_CONTENT = "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"
_OTEL_CONTENT = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"


def _install(hooks: list) -> None:
    from google.adk.telemetry.setup import maybe_set_otel_providers

    maybe_set_otel_providers(hooks)


def _gcp_hooks() -> list:
    from google.adk.telemetry.google_cloud import get_gcp_exporters

    return [get_gcp_exporters(enable_cloud_tracing=True)]


def setup(mode: Mode | None = None) -> str:
    """Configure tracing once at process start; returns the mode in effect."""
    mode = mode or os.environ.get("CHA_TRACING", "off")  # type: ignore[assignment]
    if mode not in MODES:
        raise ValueError(f"CHA_TRACING must be one of {MODES}, not {mode!r}")
    content = mode == "local" and os.environ.get("CHA_TRACE_CONTENT") == "1"
    os.environ[_ADK_CONTENT] = "true" if content else "false"
    os.environ[_OTEL_CONTENT] = "SPAN_ONLY" if content else "NO_CONTENT"
    if mode == "off":
        return mode
    os.environ.setdefault("OTEL_SERVICE_NAME", SERVICE)
    if mode == "local":
        os.environ.setdefault("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", PHOENIX)
        _install([])
    else:
        _install(_gcp_hooks())
    return mode


def args_sha(args: Any) -> str:
    text = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def annotate_tool(args: dict, response: Any) -> None:
    """Add receipt id and an args hash to the current (tool) span, if one is recording."""
    from opentelemetry import trace

    span = trace.get_current_span()
    if not span.is_recording():
        return
    span.set_attribute("cha.args_sha", args_sha(args))
    if isinstance(response, dict) and isinstance(response.get("receipt"), str):
        span.set_attribute("cha.receipt_id", response["receipt"])


def tracer() -> Any:
    from opentelemetry import trace

    return trace.get_tracer("health_agents")
