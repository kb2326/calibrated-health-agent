"""The web app: the agent over AG-UI at /api/agent, plus receipt and scoreboard routes.

Modes:
- `local`: the laptop, real data (Vertex AI only). Answers only on 127.0.0.1 / localhost,
  so a page on another site can't read it through DNS rebinding.
- `demo`: the synthetic eval fixture, same host rule, a "demo data" flag for screenshots.
- `cloud`: Cloud Run behind IAP (Task 13).
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from typing import Literal

from ag_ui_adk import add_adk_fastapi_endpoint
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google.adk.models import BaseLlm
from health_agents import tracing
from health_core.settings import Settings, get_settings

from . import routes
from .agent import build_agent

Mode = Literal["local", "demo", "cloud"]
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})
# The statically exported Next.js app; in the container image CHA_WEB_STATIC points at it.
DEFAULT_STATIC = Path(os.environ.get("CHA_WEB_STATIC") or Path(__file__).resolve().parents[4] / "apps" / "web" / "out")
NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>Calibrated Health Agent</title>
<p>The front end isn't built yet. Run <code>npm ci &amp;&amp; npm run build</code> in
<code>apps/web</code>, then reload. The agent API is up at <code>/api</code>.</p>"""


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(self), camera=(), microphone=(), payment=()",
}
_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)


def content_security_policy(static: Path) -> str:
    """'self' only, plus the exact inline scripts the static export contains, by hash.

    Next.js puts a few small inline scripts in each exported page; allowing them by SHA-256
    keeps the policy strict (no 'unsafe-inline'), and any other injected script is refused.
    """
    hashes: set[str] = set()
    if static.is_dir():
        for page in static.rglob("*.html"):
            for body in _INLINE_SCRIPT.findall(page.read_text(encoding="utf-8", errors="replace")):
                digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
                hashes.add(f"'sha256-{digest}'")
    scripts = " ".join(["'self'", *sorted(hashes)])
    return ("default-src 'self'; "
            f"script-src {scripts}; "
            "style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "manifest-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'")


def _host(request: Request) -> str:
    host = request.headers.get("host", "")
    if host.startswith("["):  # [::1]:8780
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0]


IAP_USER = "x-goog-authenticated-user-email"


def iap_email(request: Request) -> str | None:
    """The account IAP signed in, from its header ("accounts.google.com:me@example.com")."""
    value = request.headers.get(IAP_USER, "")
    prefix = "accounts.google.com:"
    return value[len(prefix):].lower() if value.startswith(prefix) else None


def refresh_health_db(settings: Settings) -> None:
    """Cloud mode reads health.db from the bucket; download only when the job published a
    new generation since the last pull. The web never pushes health.db."""
    from health_data import db, store

    if not settings.db_bucket:
        return
    gen_path = settings.data_dir / ".web_health_generation"
    remote = store.remote_generation(settings.db_bucket, settings.db_object)
    if remote is not None and remote == store.recorded_generation(gen_path=gen_path) and db.DB_PATH.exists():
        return
    store.pull_db(settings.db_bucket, settings.db_object, db.DB_PATH, gen_path=gen_path)


def create_app(mode: Mode, *, model: BaseLlm | str | None = None, topology: str | None = None,
               models: dict[str, BaseLlm | str] | None = None,
               static_dir: Path | None = None) -> FastAPI:
    settings = get_settings()
    owner = (settings.web_owner_email or "").strip().lower()
    if mode == "cloud" and not owner:
        raise ValueError("cloud mode needs CHA_WEB_OWNER_EMAIL: the one owner account IAP may let in")
    stack = ExitStack()
    if mode == "demo":  # point every tool at the synthetic fixture for the app's lifetime
        from health_eval.runner import eval_fixture

        stack.enter_context(eval_fixture())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            stack.close()

    api = FastAPI(title="Calibrated Health Agent", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    api.state.mode = mode

    if mode in ("local", "demo"):
        @api.middleware("http")
        async def local_only(request: Request, call_next):
            if _host(request) not in LOCAL_HOSTS:
                return JSONResponse({"error": "This server answers only on localhost."},
                                    status_code=403)
            return await call_next(request)
    else:
        @api.middleware("http")
        async def owner_only(request: Request, call_next):
            # IAP already refuses everyone else; this is the second lock, in our own code.
            if iap_email(request) != owner:
                return JSONResponse({"error": "Sign in with the owner's Google account."},
                                    status_code=403)
            if request.url.path == "/api/agent" or request.url.path.startswith("/api/receipts"):
                import asyncio

                await asyncio.to_thread(refresh_health_db, settings)
            return await call_next(request)

    static = static_dir or DEFAULT_STATIC
    csp = content_security_policy(static)

    @api.middleware("http")
    async def headers_and_span(request: Request, call_next):
        # One span per request: the route template and status only, never the path's values,
        # the query string or a body.
        with tracing.span("cha.web.request") as span:
            response = await call_next(request)
            route = request.scope.get("route")
            span.set_attribute("http.route", getattr(route, "path", None) or "static")
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.status_code", response.status_code)
        response.headers.update(SECURITY_HEADERS)
        response.headers["Content-Security-Policy"] = csp
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    api.include_router(routes.router)
    add_adk_fastapi_endpoint(api, build_agent(topology=topology, model=model, models=models),
                             path="/api/agent")
    if (static / "index.html").exists():  # mounted last, so /api/* always wins
        api.mount("/", StaticFiles(directory=static, html=True), name="web")
    else:
        @api.get("/", include_in_schema=False)
        def not_built() -> HTMLResponse:
            return HTMLResponse(NOT_BUILT)
    return api
