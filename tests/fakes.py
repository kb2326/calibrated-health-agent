"""A fake Google Health discovery service for tests: no network, no credentials."""
from __future__ import annotations

from typing import Any


class FakeRequest:
    def __init__(self, method_id: str, payload: Any = None, error: Exception | None = None):
        self.methodId = method_id
        self.payload = payload
        self.error = error

    def execute(self):
        if self.error is not None:
            raise self.error
        return self.payload


class FakePoints:
    """`dataPoints` collection. `responses` maps method -> list of pages (dicts)."""

    def __init__(self, responses: dict[str, list[dict]]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def _req(self, method: str, kwargs: dict) -> FakeRequest:
        self.calls.append((method, kwargs))
        pages = self.responses.get(method, [{}])
        req = FakeRequest(f"health.users.dataTypes.dataPoints.{method}", pages[0])
        req.pages = pages  # type: ignore[attr-defined]
        req.index = 0  # type: ignore[attr-defined]
        return req

    def _next(self, request, response):
        nxt = request.index + 1
        if nxt >= len(request.pages) or not response.get("nextPageToken"):
            return None
        out = FakeRequest(request.methodId, request.pages[nxt])
        out.pages, out.index = request.pages, nxt  # type: ignore[attr-defined]
        return out

    def reconcile(self, **kw):
        return self._req("reconcile", kw)

    def reconcile_next(self, request, response):
        return self._next(request, response)

    def list(self, **kw):
        return self._req("list", kw)

    def list_next(self, request, response):
        return self._next(request, response)

    def dailyRollUp(self, **kw):  # noqa: N802 - mirrors the discovery client
        return self._req("dailyRollUp", kw)


class FakeService:
    def __init__(self, responses: dict[str, list[dict]]):
        self.points = FakePoints(responses)

    def users(self):
        return self

    def dataTypes(self):  # noqa: N802
        return self

    def dataPoints(self):  # noqa: N802
        return self.points
