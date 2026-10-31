"""Strip raw tool rows from the AG-UI event stream before it reaches the browser.

The browser sees which tool ran, whether it worked, how many rows, and the receipt id.
The data behind a receipt loads only through GET /api/receipts/{id}. The model's own answer
text passes through: what it states is what the person asked for.
"""
from __future__ import annotations

import json
from typing import Any

from ag_ui.core import (
    BaseEvent,
    MessagesSnapshotEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
    ToolMessage,
)

STATE_KEYS = ("turn_receipts", "verify_attempts")
ERROR_MAX = 200


def _receipt_ids(value: Any) -> Any:
    """turn_receipts entries carry outputs; the browser gets the ids only."""
    if isinstance(value, list):
        return [x for x in (_receipt_ids(v) for v in value) if x is not None]
    if isinstance(value, dict):
        rid = value.get("receipt")
        return rid if isinstance(rid, str) else None
    return value if isinstance(value, str) else None


def summarise_result(tool: str | None, content: Any) -> str:
    """Content that isn't a JSON object (text, content parts) reveals nothing but the tool."""
    try:
        body = json.loads(content) if isinstance(content, str) else None
    except ValueError:
        body = None
    out: dict[str, Any] = {"tool": tool, "receipt": None, "status": "ok", "n": None, "error": None}
    if isinstance(body, dict):
        rid = body.get("receipt")
        out["receipt"] = rid if isinstance(rid, str) else None
        n = body.get("n")
        out["n"] = n if isinstance(n, int) and not isinstance(n, bool) else None
        if "error" in body:
            out["status"] = "error"
            out["error"] = str(body["error"])[:ERROR_MAX]
    return json.dumps(out)


def _allowed_path(path: str) -> str | None:
    key = path.lstrip("/").split("/", 1)[0]
    return key if key in STATE_KEYS else None


class StreamFilter:
    """Stateful per run: remembers tool names by call id so results can be labelled."""

    def __init__(self) -> None:
        self.names: dict[str, str] = {}

    def __call__(self, event: BaseEvent) -> BaseEvent | None:
        if isinstance(event, ToolCallStartEvent):
            self.names[event.tool_call_id] = event.tool_call_name
            return event
        if isinstance(event, ToolCallResultEvent):
            name = self.names.get(event.tool_call_id)
            return event.model_copy(update={"content": summarise_result(name, event.content)})
        if isinstance(event, StateDeltaEvent):
            ops = []
            for op in event.delta or []:
                if hasattr(op, "model_dump"):  # JSON Patch ops arrive as pydantic models
                    op = op.model_dump(mode="json", exclude_none=True)
                if not isinstance(op, dict):
                    continue
                key = _allowed_path(str(op.get("path", "")))
                if key is None:
                    continue
                op = dict(op)
                if key == "turn_receipts" and "value" in op:
                    op["value"] = _receipt_ids(op["value"])
                ops.append(op)
            return event.model_copy(update={"delta": ops}) if ops else None
        if isinstance(event, StateSnapshotEvent):
            snap = event.snapshot if isinstance(event.snapshot, dict) else {}
            kept = {k: snap[k] for k in STATE_KEYS if k in snap}
            if "turn_receipts" in kept:
                kept["turn_receipts"] = _receipt_ids(kept["turn_receipts"])
            return event.model_copy(update={"snapshot": kept})
        if isinstance(event, MessagesSnapshotEvent):
            names = dict(self.names)
            for m in event.messages:
                for tc in getattr(m, "tool_calls", None) or []:
                    names[tc.id] = tc.function.name
            msgs = []
            for m in event.messages:
                if isinstance(m, ToolMessage):
                    m = m.model_copy(update={"content": summarise_result(
                        names.get(m.tool_call_id), m.content)})
                msgs.append(m)
            return event.model_copy(update={"messages": msgs})
        return event
