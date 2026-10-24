"""ADK's Gemini model reaches Vertex AI (global endpoint, project from Settings), never an API key."""
from __future__ import annotations

from health_agents import vertex


def test_configure_sets_vertex_env_from_settings(monkeypatch):
    for k in ("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"):
        monkeypatch.delenv(k, raising=False)
    vertex.configure()
    import os
    assert os.environ["GOOGLE_GENAI_USE_VERTEXAI"] == "true"
    assert os.environ["GOOGLE_CLOUD_PROJECT"] == "artful-timing-506108-n8"
    assert os.environ["GOOGLE_CLOUD_LOCATION"] == "global"


def test_investigator_configures_vertex_before_running(monkeypatch):
    from health_agents import investigator

    called = []
    monkeypatch.setattr(investigator.vertex, "configure", lambda: called.append(True))
    monkeypatch.setattr(investigator, "_uncovered", lambda conn: [])
    investigator.run_investigation(None, __import__("datetime").datetime.now().astimezone())  # type: ignore[arg-type]
    assert called == [True]
