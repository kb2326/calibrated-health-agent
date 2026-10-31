# ADR 0006: Traces carry no message content outside the laptop

**Status:** accepted and deployed, 2026-10-30

## Context

ADK's OpenTelemetry instrumentation can record prompts, replies and tool arguments on spans.
For this agent those contain health data. ADK's legacy span content
(`ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS`) defaults to **on**.

## Decision

- `health_agents.tracing.setup()` runs once per process and sets **both** content switches
  explicitly every time (`ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS`,
  `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`).
- `cloud` mode (the Cloud Run job): content is always off, whatever the environment says.
- `local` mode (Phoenix on the laptop): content is off unless `CHA_TRACE_CONTENT=1`, so the
  data never leaves the machine.
- Our own attributes carry ids and hashes only: `cha.receipt_id` and `cha.args_sha` (a hash of
  the arguments) on tool spans, `cha.usd` on turns, and name, duration and status on job steps.

## Consequences

- Traces show structure, timing, tokens, cost and errors. Debugging content means
  reproducing locally with Phoenix.
- `tests/test_tracing.py` runs a real turn into an in-memory exporter and checks that neither
  the SQL nor the question appears in any span attribute.
- Deploying it surfaced two real requirements of Google's Telemetry API. The OTel resource must
  carry `gcp.project_id` (otherwise every batch gets HTTP 400). Trace storage needs
  `observability.googleapis.com` (the `_Trace` bucket). Both are now in code and Terraform.
