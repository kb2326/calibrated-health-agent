# ADR 0004: A local subprocess sandbox for model-written Python

**Status:** accepted (Phase 3), 2026-10-30

## Context

The agent writes Python to compute what SQL can't express (medians, trends, correlations
with lags). That code is untrusted: a prompt injection could try to read files, open sockets
or run processes. Options were a hosted code executor (Vertex AI code execution, a container
service), a VM or gVisor locally, or a hardened subprocess.

## Decision

A fresh child process for every call (`health_agents.sandbox`), with defence in depth:

1. A static policy check refuses dangerous imports and attributes before anything runs.
2. The child starts with `-s -P` in an empty temp directory, with a scrubbed environment (no
   credentials, no project settings).
3. An audit hook in the child blocks network, process creation, ctypes and file writes. Module
   proxies hide dangerous attributes.
4. Resource limits on Linux (CPU, address space, file size, process count), a 15 s
   wall-clock timeout and an output cap.
5. The child never opens the database. Data arrives as a JSON bundle, with journal notes
   already wrapped as untrusted text.

In the cloud job, Cloud Run's gVisor sits underneath as a second boundary.

## Why not a hosted executor

Cost (the project runs under $1/month) and data locality: real health data must not leave the
owner's project or laptop. A hosted executor would add a copy of the data in another service.

## Consequences

- Red-team `sandbox_escape` cases are refused without a model (`tests/test_eval_redteam.py`
  runs them directly against `sandbox.run`).
- **Residual risk:** this is not a VM boundary. A CPython audit-hook bypass would defeat it,
  and on Windows there is no memory limit (only the timeout). Documented in
  `docs/threat-model.md`.
