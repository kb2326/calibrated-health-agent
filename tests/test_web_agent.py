"""The ADK workflow served over AG-UI (Phase 5 Task 1 and 3a), offline with FakeLlm."""
from __future__ import annotations

import json
import uuid

import pytest
from agent_fakes import FakeLlm, call, text
from fastapi.testclient import TestClient
from health_agents import tools
from health_core.settings import Settings
from health_data import db, store

pytest.importorskip("ag_ui_adk")
from health_web import agent as web_agent  # noqa: E402
from health_web.app import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def fixture_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(store, "_gen_path", lambda p: tmp_path / ".db_generation")
    monkeypatch.setattr(tools, "get_settings", lambda: Settings.model_validate({"db_bucket": None}))
    db.init_db()
    with db.connect() as conn:
        for i, v in enumerate((60, 62, 64)):
            conn.execute("INSERT INTO daily_metrics (date, data_type, agg_value, n_points, source)"
                         " VALUES (?, 'heart-rate', ?, 1, '')", (f"2026-10-2{i}", v))


def run_input(question: str, *, state: dict | None = None, thread: str | None = None) -> dict:
    return {"threadId": thread or uuid.uuid4().hex, "runId": uuid.uuid4().hex,
            "state": state or {}, "messages": [{"id": uuid.uuid4().hex, "role": "user",
                                                 "content": question}],
            "tools": [], "context": [], "forwardedProps": {}}


def stream(client: TestClient, body: dict) -> list[dict]:
    events = []
    with client.stream("POST", "/api/agent", json=body,
                       headers={"accept": "text/event-stream"}) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events


def answer_text(events: list[dict]) -> str:
    return "".join(e.get("delta", "") for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")


def test_single_topology_streams_run_text_and_tool_events():
    llm = FakeLlm([call("run_sql", query="SELECT AVG(agg_value) AS m, COUNT(*) AS n FROM daily_metrics"),
                   text("Your heart rate averaged in the low sixties.")])
    client = TestClient(create_app("local", model=llm))
    events = stream(client, run_input("How is my heart rate?"))
    types_ = [e["type"] for e in events]
    assert types_[0] == "RUN_STARTED" and types_[-1] == "RUN_FINISHED"
    starts = [e for e in events if e["type"] == "TOOL_CALL_START"]
    assert [e["toolCallName"] for e in starts] == ["run_sql"]
    assert answer_text(events)


def test_team_topology_streams_and_may_call_a_specialist():
    coach = FakeLlm([text("Keep it light today.")])
    main = FakeLlm([call("coach", request="Hard workout today?"),
                    text("Take it easy today; the coach suggests a light session.")])
    client = TestClient(create_app("local", model=main, topology="team", models={"coach": coach}))
    events = stream(client, run_input("Should I train hard today?"))
    assert events[-1]["type"] == "RUN_FINISHED"
    assert coach.calls == 1 and "light session" in answer_text(events)


def test_client_state_cannot_reach_internal_keys():
    """Only a validated `location` passes from the browser into the ADK session."""
    clean = web_agent.sanitise_state({
        "turn_outputs": [{"m": 99}], "last_draft": "x", "verify_attempts": 5,
        "location": {"latitude": 13.08, "longitude": 80.27, "place": "Chennai", "evil": 1}})
    assert clean == {"location": {"latitude": 13.08, "longitude": 80.27, "place": "Chennai"}}


@pytest.mark.parametrize("loc", [
    {"latitude": "13", "longitude": 80}, {"latitude": 91, "longitude": 80},
    {"latitude": 13, "longitude": -181}, {"latitude": float("nan"), "longitude": 1},
    {"latitude": True, "longitude": 1}, "Chennai", None])
def test_bad_locations_are_dropped(loc):
    assert web_agent.sanitise_state({"location": loc}) == {}


def test_place_is_trimmed():
    out = web_agent.sanitise_state({"location": {"latitude": 1, "longitude": 2, "place": "x" * 200}})
    assert len(out["location"]["place"]) == 60


def test_location_from_run_state_reaches_weather_tool(monkeypatch):
    from health_data import weather

    seen = []
    monkeypatch.setattr(weather, "forecast", lambda lat, lon, **k: seen.append((lat, lon)) or [])
    llm = FakeLlm([call("weather"), text("It looks dry today.")])
    client = TestClient(create_app("local", model=llm))
    stream(client, run_input("Weather today?", state={
        "location": {"latitude": 13.08, "longitude": 80.27, "place": "Chennai"},
        "turn_outputs": [{"x": 1}]}))
    assert seen == [(13.08, 80.27)]


def test_no_location_uses_home(monkeypatch):
    from health_data import weather

    seen = []
    monkeypatch.setattr(weather, "forecast", lambda lat, lon, **k: seen.append((lat, lon)) or [])
    client = TestClient(create_app("local", model=FakeLlm([call("weather"), text("Dry.")])))
    stream(client, run_input("Weather today?"))
    assert seen == [(pytest.approx(11.341), pytest.approx(77.7172))]
