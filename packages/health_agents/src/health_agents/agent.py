"""ADK entry point: `root_agent` is the chat workflow in the configured topology.

`CHA_TOPOLOGY=single` (default until the Phase 4 evals pick a winner) or `multi`. The
multi topology follows Google Research's Personal Health Agent (data scientist, domain
expert, coach); the single agent is its comparison. See `workflow.py` and ADR 0001.

Read-only by construction: tools open SQLite in `mode=ro` behind an authorizer, Python
runs in the sandbox, and every API call passes the client's method allowlist.
"""
from __future__ import annotations

from health_core.settings import get_settings

from .workflow import build_workflow

MODEL = get_settings().model_default

root_agent = build_workflow(get_settings().topology)
