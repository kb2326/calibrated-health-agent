# Observability

Tracing uses ADK's built-in OpenTelemetry instrumentation (agent, model and tool spans,
GenAI semantic conventions), configured once per process by `health_agents.tracing.setup()`.

| `CHA_TRACING` | Where spans go | Message content |
|---|---|---|
| `off` (default) | nowhere | — |
| `local` | Phoenix on the laptop, OTLP over HTTP (`http://localhost:6006/v1/traces`) | off; on only with `CHA_TRACE_CONTENT=1` |
| `cloud` | Cloud Trace, via ADK's exporter to `telemetry.googleapis.com` (the Cloud Run job) | always off, whatever the environment says |

`setup()` sets both content switches on every start:
`ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS`, which defaults to on in ADK, and
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`. With content off, ADK still records
tool names, ids, timings, token counts and errors, but writes `{}` in place of the prompt,
the reply and the tool arguments.

## What our spans add

- On every tool span: `cha.receipt_id` (the receipt behind any number the tool returned) and
  `cha.args_sha`, a 16-character hash of the arguments. You can see that two calls had the
  same arguments without seeing what they were.
- A `cha.turn` span around each chat turn, with `cha.usd` (list-price cost) and
  `cha.receipts` (how many receipts the turn produced).
- In the web app, a `cha.web.request` span per request with `http.route` (the route
  template, never path values), `http.method` and `http.status_code`; never the query string
  or a body (`tests/test_web_security.py`).

`tests/test_tracing.py` runs a real turn into an in-memory exporter. It checks that neither
the SQL nor the question appears in any span attribute, and that the receipt id does.

## Local: Phoenix

```bash
docker run -p 6006:6006 arizephoenix/phoenix      # UI at http://localhost:6006
CHA_TRACING=local uv run cha ask "How did I sleep this week?"
# to see prompts and replies too (laptop only):
CHA_TRACING=local CHA_TRACE_CONTENT=1 uv run cha chat
```

Phoenix is a separate container, so it adds no Python dependency.

## Cloud: Cloud Trace

The job runs with `CHA_TRACING=cloud`. Its service account holds `roles/cloudtrace.agent`
and `roles/telemetry.tracesWriter`. Three APIs are enabled: `cloudtrace.googleapis.com`,
`telemetry.googleapis.com` (the OTLP endpoint ADK exports to) and
`observability.googleapis.com` (the `_Trace` storage bucket behind it). See `infra/iam.tf`,
`infra/services.tf` and `infra/job.tf`.

The Telemetry API rejects spans whose OTel resource does not name the project (HTTP 400, "Failed
to export span batch"). So cloud mode passes ADK's `get_gcp_resource(project)`, which sets
`gcp.project_id`, the way ADK's own API server does.

Besides ADK's agent spans, the job writes a `cha.job` root span and one `job.<step>` span per
step (pull, migrate, sync, journal, lock, settle, retest, investigate, push, publish,
heartbeat). They carry only the step name, its duration and its status, never the step's
output.
The nightly job writes a few hundred spans a month, well inside Cloud Trace's free
allowance (2.5M spans/month), so it costs $0.

Applying these Terraform changes is a deploy and waits for the owner's yes.
