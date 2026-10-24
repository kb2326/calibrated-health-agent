"""Point ADK's Gemini models at Vertex AI with ambient credentials (never an API key).

ADK builds its own `google.genai` client from environment variables. The laptop CLI and the
cloud job both call `configure()` before running an agent, so the model is reached on the
project and location in `Settings` (the global endpoint serves Gemini 3.5 models).
Values already set in the environment win.
"""
from __future__ import annotations

import os

from health_core.settings import get_settings


def configure() -> None:
    settings = get_settings()
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", settings.gcp_project)
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", settings.vertex_location)
