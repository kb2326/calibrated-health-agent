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

from opentelemetry.sdk.trace import SpanProcessor

Mode = Literal["off", "local", "cloud"]
MODES = ("off", "local", "cloud")
PHOENIX = "http://localhost:6006/v1/traces"
SERVICE = "calibrated-health-agent"
_ADK_CONTENT = "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"
_OTEL_CONTENT = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"


class ScrubExceptions(SpanProcessor):
    """Reduce every recorded exception to its type.

    OTel's `record_exception` stores the message and the full traceback (chained causes
    included), and ADK's tool spans call it directly, bypassing the content switches. An
    exception message can carry health data (a journal answer, a row value), so outside local
    content mode only `exception.type` survives.
    """

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        def record_exception(exception: BaseException, attributes: Any = None,
                             timestamp: int | None = None, escaped: bool = False) -> None:
            span.add_event("exception", {"exception.type": type(exception).__name__}, timestamp)

        span.record_exception = record_exception

    def on_end(self, span: Any) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def _scrub_hooks() -> list:
    from google.adk.telemetry.setup import OTelHooks

    return [OTelHooks(span_processors=[ScrubExceptions()])]


def _install(hooks: list, resource: Any = None) -> None:
    from google.adk.telemetry.setup import maybe_set_otel_providers

    maybe_set_otel_providers(hooks, otel_resource=resource)


def _gcp_resource() -> Any:
    """The OTel resource naming the project: telemetry.googleapis.com rejects spans without
    `gcp.project_id` (HTTP 400), so cloud mode must pass it, as ADK's own server does."""
    from google.adk.telemetry.google_cloud import get_gcp_resource

    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("CHA_GCP_PROJECT")
    if not project:
        import google.auth

        project = google.auth.default()[1]
    return get_gcp_resource(project)


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
        _install([] if content else _scrub_hooks())
    else:
        _install([*_scrub_hooks(), *_gcp_hooks()], _gcp_resource())
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


def error_status(description: str) -> Any:
    from opentelemetry.trace import Status, StatusCode

    return Status(StatusCode.ERROR, description)


def span(name: str) -> Any:
    """Our own spans: never record exception text, never overwrite our status."""
    return tracer().start_as_current_span(name, record_exception=False,
                                          set_status_on_exception=False)


def tracer() -> Any:
    from opentelemetry import trace

    return trace.get_tracer("health_agents")
