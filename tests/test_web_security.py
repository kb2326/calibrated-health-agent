"""Security headers and request tracing for the web app (Phase 5 Task 11)."""
from __future__ import annotations

import base64
import hashlib

from agent_fakes import FakeLlm, text
from health_web.app import create_app
from test_web_agent import fixture_db, local_client  # noqa: F401

INLINE = "self.__next_f=self.__next_f||[]"


def _static(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "index.html").write_text(
        f'<html><head><script src="/_next/a.js"></script></head><body><script>{INLINE}</script></body></html>')
    return out


def test_security_headers_with_hashed_inline_scripts_only(tmp_path):
    client = local_client(create_app("local", model=FakeLlm([text("x")]), static_dir=_static(tmp_path)))
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    digest = base64.b64encode(hashlib.sha256(INLINE.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    for part in ("default-src 'self'", "connect-src 'self'", "frame-ancestors 'none'",
                 "object-src 'none'", "base-uri 'none'"):
        assert part in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "geolocation=(self)" in r.headers["permissions-policy"]
    assert r.headers["x-frame-options"] == "DENY"


def test_api_responses_carry_the_headers_too(tmp_path):
    client = local_client(create_app("local", model=FakeLlm([text("x")]), static_dir=_static(tmp_path)))
    r = client.get("/api/health")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"  # health data is never cached


def test_request_span_has_route_and_status_but_no_body(tmp_path, monkeypatch):
    from health_web import app as app_mod

    spans: list[dict] = []

    class FakeSpan:
        def __init__(self, name):
            self.attrs = {"name": name}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            spans.append(self.attrs)
            return False

        def set_attribute(self, k, v):
            self.attrs[k] = v

        def set_status(self, *_):
            pass

    monkeypatch.setattr(app_mod.tracing, "span", lambda name: FakeSpan(name))
    client = local_client(create_app("local", model=FakeLlm([text("x")]), static_dir=_static(tmp_path)))
    client.get("/api/receipts/r-0000000000?secret=ask-about-my-sleep")
    span = next(s for s in spans if s["name"] == "cha.web.request")
    assert span["http.route"] == "/api/receipts/{receipt_id}"
    assert span["http.status_code"] == 404
    assert "ask-about-my-sleep" not in repr(span) and "r-0000000000" not in repr(span)


def test_external_scripts_are_not_hashed_as_inline(tmp_path):
    from health_web.app import content_security_policy

    out = tmp_path / "o"
    out.mkdir()
    (out / "index.html").write_text('<script src="/a.js"></script><script>x()</script>')
    csp = content_security_policy(out)
    empty = base64.b64encode(hashlib.sha256(b"").digest()).decode()
    assert f"'sha256-{empty}'" not in csp  # the src tag's empty body is not an inline script
    assert csp.count("'sha256-") == 1


def test_ag_ui_adk_state_route_is_not_exposed(tmp_path):
    """Review I1: ag_ui_adk also mounts POST /agents/state, which returns the raw session."""
    client = local_client(create_app("local", model=FakeLlm([text("x")]), static_dir=_static(tmp_path)))
    assert client.post("/agents/state", json={"threadId": "t"}).status_code in (404, 405)
    paths = {getattr(r, "path", "") for r in client.app.router.routes}  # type: ignore[attr-defined]
    assert paths & {"/agents/state"} == set()
