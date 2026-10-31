"""No raw tool rows reach the browser (Phase 5 Task 2)."""
from __future__ import annotations

import json
from typing import Any

from ag_ui.core import (
    EventType,
    MessagesSnapshotEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from agent_fakes import FakeLlm, call, text
from health_web.stream import StreamFilter
from test_web_agent import answer_text, fixture_db, local_client, run_input, stream  # noqa: F401


def _any(x: Any) -> Any:
    return x


ROWS = {"rows": [{"v": 41.0}], "n": 1, "truncated": False, "receipt": "r-c06cd4de3a"}


def _start(f: Any, name="run_sql", cid="c1"):
    return f(ToolCallStartEvent(type=EventType.TOOL_CALL_START, tool_call_id=cid, tool_call_name=name))


def test_tool_result_keeps_receipt_drops_rows():
    f: Any = StreamFilter()
    _start(f)
    out = f(ToolCallResultEvent(type=EventType.TOOL_CALL_RESULT, message_id="m", tool_call_id="c1",
                                content=json.dumps(ROWS)))
    assert out is not None
    body = json.loads(out.content)
    assert body == {"tool": "run_sql", "receipt": "r-c06cd4de3a", "status": "ok", "n": 1, "error": None}
    assert "41" not in out.content


def test_tool_error_is_kept_as_a_short_message():
    f: Any = StreamFilter()
    _start(f, "query_metric")
    out = f(ToolCallResultEvent(type=EventType.TOOL_CALL_RESULT, message_id="m", tool_call_id="c1",
                                content=json.dumps({"error": "start and end must be real dates"})))
    assert out is not None and json.loads(out.content)["status"] == "error"
    assert json.loads(out.content)["error"] == "start and end must be real dates"


def test_non_json_tool_result_reveals_nothing():
    f: Any = StreamFilter()
    _start(f, "coach")
    out = f(ToolCallResultEvent(type=EventType.TOOL_CALL_RESULT, message_id="m", tool_call_id="c1",
                                content="Your resting HR was 58 so take it easy"))
    assert out is not None and "58" not in out.content


def test_state_delta_allowlist_and_receipts_reduced_to_ids():
    f: Any = StreamFilter()
    out = f(StateDeltaEvent(type=EventType.STATE_DELTA, delta=_any([
        {"op": "add", "path": "/turn_receipts", "value": [{"receipt": "r-1", "output": [{"v": 41}]}]},
        {"op": "add", "path": "/turn_outputs", "value": [ROWS]},
        {"op": "add", "path": "/last_draft", "value": "41"},
        {"op": "replace", "path": "/verify_attempts", "value": 1}])))
    assert out is not None
    assert out.delta == [{"op": "add", "path": "/turn_receipts", "value": ["r-1"]},
                         {"op": "replace", "path": "/verify_attempts", "value": 1}]


def test_state_delta_with_nothing_allowed_is_dropped():
    f: Any = StreamFilter()
    assert f(StateDeltaEvent(type=EventType.STATE_DELTA, delta=_any([
        {"op": "add", "path": "/turn_outputs", "value": [ROWS]}]))) is None


def test_state_snapshot_allowlist():
    f: Any = StreamFilter()
    out = f(StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot={
        "question": "q", "turn_outputs": [ROWS], "turn_receipts": [{"receipt": "r-1", "output": [1]}],
        "verify_attempts": 0, "location": {"latitude": 1, "longitude": 2}}))
    assert out is not None and out.snapshot == {"turn_receipts": ["r-1"], "verify_attempts": 0}


def test_messages_snapshot_tool_content_reduced():
    f: Any = StreamFilter()
    out = f(MessagesSnapshotEvent(type=EventType.MESSAGES_SNAPSHOT, messages=_any([
        {"id": "a", "role": "assistant", "content": "", "toolCalls": [
            {"id": "c9", "type": "function", "function": {"name": "run_sql", "arguments": "{}"}}]},
        {"id": "t", "role": "tool", "toolCallId": "c9", "content": json.dumps(ROWS)}])))
    assert out is not None
    tool_msg = out.messages[1]
    assert "41" not in tool_msg.content and json.loads(tool_msg.content)["receipt"] == "r-c06cd4de3a"


def test_text_passes_through():
    f: Any = StreamFilter()
    ev = TextMessageContentEvent(type=EventType.TEXT_MESSAGE_CONTENT, message_id="m", delta="58 bpm")
    assert f(ev) is ev


def test_end_to_end_stream_has_no_fixture_values():
    from health_web.app import create_app

    llm = FakeLlm([call("run_sql", query="SELECT agg_value AS v FROM daily_metrics ORDER BY date"),
                   text("Here is your heart rate.")])
    events = stream(local_client(create_app("local", model=llm)), run_input("Heart rate?"))
    raw = json.dumps([e for e in events if e["type"] != "TOOL_CALL_ARGS"])
    for value in ("60.0", "62.0", "64.0"):
        assert value not in raw, value
    result = next(e for e in events if e["type"] == "TOOL_CALL_RESULT")
    assert json.loads(result["content"])["receipt"].startswith("r-")
    assert answer_text(events) == "Here is your heart rate."


def test_reasoning_events_never_reach_the_browser():
    from ag_ui.core import BaseEvent

    f = StreamFilter()
    for t in ("REASONING_START", "REASONING_MESSAGE_CONTENT", "REASONING_ENCRYPTED_VALUE", "REASONING_END"):
        ev = BaseEvent.model_construct(type=t)
        assert f(ev) is None, t
