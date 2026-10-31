"""The web app: the agent over AG-UI at /api/agent (more routes in later tasks)."""
from __future__ import annotations

from typing import Literal

from ag_ui_adk import add_adk_fastapi_endpoint
from fastapi import FastAPI
from google.adk.models import BaseLlm

from .agent import build_agent

Mode = Literal["local", "demo", "cloud"]


def create_app(mode: Mode, *, model: BaseLlm | str | None = None, topology: str | None = None,
               models: dict[str, BaseLlm | str] | None = None) -> FastAPI:
    api = FastAPI(title="Calibrated Health Agent", docs_url=None, redoc_url=None, openapi_url=None)
    api.state.mode = mode
    add_adk_fastapi_endpoint(api, build_agent(topology=topology, model=model, models=models),
                             path="/api/agent")
    return api
