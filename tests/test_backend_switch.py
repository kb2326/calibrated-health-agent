"""CI reaches Gemini through an AI Studio key without changing Phase 3 code: existing env wins."""
from __future__ import annotations

import os

from health_agents import vertex


def test_existing_env_wins_over_vertex_defaults(monkeypatch):
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "false")
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    vertex.configure()
    assert os.environ["GOOGLE_GENAI_USE_VERTEXAI"] == "false"
    assert os.environ["GOOGLE_API_KEY"] == "x"
