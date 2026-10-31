"""Receipt, re-run, scoreboard and health routes; laptop and demo modes (Phase 5 Task 3)."""
from __future__ import annotations

import pytest
from agent_fakes import FakeLlm, text
from fastapi.testclient import TestClient
from health_agents import agent_db, receipts
from health_web.app import create_app
from health_web.describe import describe_receipt
from test_web_agent import fixture_db, local_client  # noqa: F401

SQL = "SELECT AVG(agg_value) AS m FROM daily_metrics WHERE data_type = 'heart-rate'"


def _app():
    return create_app("local", model=FakeLlm([text("x")]))


def _receipt(code: str = SQL, output=None) -> str:
    with agent_db.connect() as conn:
        return receipts.record(conn, kind="sql", code=code, data_hash=receipts.rows_hash(output or [{"m": 62.0}]),
                               as_of="2026-10-22", output=output or [{"m": 62.0}],
                               executor="sqlite-ro/1", context="chat")


def test_receipt_route_returns_code_output_and_description():
    rid = _receipt()
    r = local_client(_app()).get(f"/api/receipts/{rid}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == rid and body["code"] == SQL and body["output"] == [{"m": 62.0}]
    assert body["description"] == "SQL over daily heart rate"
    assert {"kind", "executor", "as_of", "data_hash", "where"} <= body.keys()


@pytest.mark.parametrize("rid", ["r-0000000000", "nonsense", "r-../../etc"])
def test_unknown_receipt_is_404_with_message(rid):
    r = local_client(_app()).get(f"/api/receipts/{rid}")
    assert r.status_code == 404 and r.json() == {"error": "No such receipt"}


def test_rerun_reports_matches():
    rid = _receipt()
    r = local_client(_app()).post(f"/api/receipts/{rid}/rerun")
    assert r.status_code == 200 and r.json()["status"] == "matches"


def test_rerun_reports_differs_when_output_was_wrong():
    rid = _receipt(output=[{"m": 1.0}])
    assert local_client(_app()).post(f"/api/receipts/{rid}/rerun").json()["status"] in (
        "differs", "data_changed")


def test_rerun_unknown_is_404():
    assert local_client(_app()).post("/api/receipts/r-0000000000/rerun").status_code == 404


def test_scoreboard_marks_not_yet_below_ten():
    body = local_client(_app()).get("/api/scoreboard").json()
    assert body["primary"]["not_yet"] is True
    assert all(row["not_yet"] for row in body["forecasters"])


def test_health_route():
    assert local_client(_app()).get("/api/health").json() == {"ok": True, "mode": "local",
                                                               "demo": False}


def test_local_mode_refuses_foreign_host():
    r = TestClient(_app(), base_url="http://evil.example").get("/api/health")
    assert r.status_code == 403


def test_demo_mode_uses_fixture_and_flags_demo():
    with local_client(create_app("demo", model=FakeLlm([text("x")]))) as client:
        assert client.get("/api/health").json()["demo"] is True
        board = client.get("/api/scoreboard")
        assert board.status_code == 200


@pytest.mark.parametrize(("kind", "code", "expected"), [
    ("sql", SQL, "SQL over daily heart rate"),
    ("sql", "SELECT AVG(deep_min) FROM sleep_sessions WHERE main_sleep = 1", "SQL over your sleep sessions"),
    ("sql", "SELECT * FROM exercise_sessions e JOIN weather_daily w USING (date)",
     "SQL over your workouts and weather"),
    ("sql", "SELECT 1", "SQL query"),
    ("python", "frames['sleep_sessions']", "Python over your sleep sessions"),
    ("python", "print(1)", "Python computation"),
])
def test_describe_receipt_names_tables_and_types(kind, code, expected):
    assert describe_receipt(kind, code) == expected


def test_cli_refuses_real_data_on_a_free_key(monkeypatch):
    from health_web import cli
    from typer.testing import CliRunner

    monkeypatch.setenv("GOOGLE_API_KEY", "free-tier-key")
    for var in ("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"):
        monkeypatch.setenv(var, "x")  # vertex.configure() uses setdefault; restored after
    ran = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: ran.append(1))
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code != 0 and "Vertex" in result.output and not ran


def test_cli_refuses_a_public_bind(monkeypatch):
    from health_web import cli
    from typer.testing import CliRunner

    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)
    assert CliRunner().invoke(cli.app, ["--host", "0.0.0.0", "--demo"]).exit_code != 0
