"""Tracing: off by default, no message content in the cloud, tool spans carry ids not args."""
from __future__ import annotations

import json

import pytest
from agent_fakes import FakeLlm, call, text
from health_agents import tracing

CONTENT_VARS = ("ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS",
                "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT")


@pytest.fixture
def no_providers(monkeypatch):
    calls = []
    monkeypatch.setattr(tracing, "_install",
                        lambda hooks, resource=None: calls.append((hooks, resource)))
    monkeypatch.setattr(tracing, "_gcp_hooks", lambda: ["gcp"])
    monkeypatch.setattr(tracing, "_gcp_resource", lambda: "project-resource")
    for var in (*CONTENT_VARS, "CHA_TRACING", "CHA_TRACE_CONTENT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)
    return calls


def test_off_is_default(no_providers):
    import os

    assert tracing.setup() == "off"
    assert no_providers == []
    assert os.environ["ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"] == "false"


def test_cloud_mode_never_captures_content(no_providers, monkeypatch):
    import os

    monkeypatch.setenv("CHA_TRACE_CONTENT", "1")
    assert tracing.setup("cloud") == "cloud"
    assert os.environ["ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"] == "false"
    assert os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == "NO_CONTENT"
    assert no_providers and "gcp" in no_providers[-1][0]
    assert no_providers[-1][1] == "project-resource"  # Telemetry API needs gcp.project_id
    # content is only ever possible locally, and only when asked for
    assert tracing.setup("local") == "local"
    assert os.environ["ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"] == "true"
    assert os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] == tracing.PHOENIX
    monkeypatch.delenv("CHA_TRACE_CONTENT")
    tracing.setup("local")
    assert os.environ["ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"] == "false"
    with pytest.raises(ValueError):
        tracing.setup("loud")  # type: ignore[arg-type]


def test_tool_span_has_receipt_and_no_args(tmp_path, monkeypatch):
    from health_agents import cli
    from health_eval import runner
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider)
    monkeypatch.delenv("CHA_TRACE_CONTENT", raising=False)
    tracing.setup("off")  # content flags off; the provider above records

    secret_sql = "SELECT COUNT(*) AS n_secret_marker FROM journal_submissions"
    with runner.eval_fixture(tmp_path / "w"):
        session = cli.Session(model=FakeLlm([call("run_sql", query=secret_sql),
                                             text("You have 41 entries.")]), refresh_memory=False)
        result = session.ask("How many journal entries?", confirm=lambda _a: False)
    spans = exporter.get_finished_spans()
    tool = [s for s in spans if (s.attributes or {}).get("gen_ai.operation.name") == "execute_tool"]
    assert tool, [s.name for s in spans]
    attrs = dict(tool[0].attributes or {})
    assert attrs["cha.receipt_id"] == result.receipts[0]
    assert len(str(attrs["cha.args_sha"])) == 16
    turn = [s for s in spans if s.name == "cha.turn"]
    assert turn and "cha.usd" in (turn[0].attributes or {})
    every_value = json.dumps([dict(s.attributes or {}) for s in spans], default=str)
    assert "n_secret_marker" not in every_value
    assert "How many journal entries" not in every_value


def test_job_steps_emit_spans_without_step_output(monkeypatch):
    from jobs import sync_job
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider)
    sync_job._step("journal", lambda: {"note_text": "private_marker", "imported": 3})
    with pytest.raises(sync_job._Abort):
        sync_job._step("push", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert set(spans) >= {"job.journal", "job.push"}
    assert (spans["job.journal"].attributes or {})["cha.step"] == "journal"
    assert not spans["job.push"].status.is_ok
    assert "private_marker" not in json.dumps([dict(s.attributes or {}) for s in spans.values()])


def test_gcp_resource_names_the_project(monkeypatch):
    monkeypatch.setenv("CHA_GCP_PROJECT", "proj-123")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    attrs = dict(tracing._gcp_resource().attributes)
    assert attrs["gcp.project_id"] == "proj-123"


def _memory_provider(monkeypatch, *, scrub: bool):
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    if scrub:
        provider.add_span_processor(tracing.ScrubExceptions())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider)
    return exporter


def test_failing_job_step_puts_no_exception_text_in_spans(monkeypatch):
    # review C1: journal text in an exception message must not reach Cloud Trace
    from jobs import sync_job

    exporter = _memory_provider(monkeypatch, scrub=False)  # even without the scrubber
    with pytest.raises(sync_job._Abort):
        sync_job._step("journal", lambda: (_ for _ in ()).throw(
            ValueError("answer: I felt SECRET_MOOD_TEXT")))
    dumped = json.dumps([[dict(e.attributes or {}) for e in s.events] + [s.status.description]
                         for s in exporter.get_finished_spans()], default=str)
    assert "SECRET_MOOD_TEXT" not in dumped
    assert "ValueError" in dumped or "_Abort" in dumped or "journal" in dumped


def test_scrubber_reduces_any_recorded_exception_to_its_type(monkeypatch):
    # ADK's own tool spans call span.record_exception(error) directly
    exporter = _memory_provider(monkeypatch, scrub=True)
    with tracing.tracer().start_as_current_span("adk.tool") as span:
        span.record_exception(RuntimeError("row value 63.4 SECRET_ROW"))
    events = exporter.get_finished_spans()[0].events
    assert [dict(e.attributes or {}) for e in events] == [{"exception.type": "RuntimeError"}]


def test_cloud_setup_installs_the_scrubber(no_providers):
    tracing.setup("cloud")
    hooks = no_providers[-1][0]
    assert any(isinstance(p, tracing.ScrubExceptions)
               for h in hooks if hasattr(h, "span_processors") for p in h.span_processors)
