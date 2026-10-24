"""Offline stand-ins for the agent layer: a scripted LLM that records every prompt, and a
deterministic embedder. No network, no credentials."""
from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncGenerator, Callable
from typing import Any

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import PrivateAttr

Step = LlmResponse | Callable[[LlmRequest], LlmResponse]


def _usage(prompt: int = 100, out: int = 20) -> types.GenerateContentResponseUsageMetadata:
    return types.GenerateContentResponseUsageMetadata(
        prompt_token_count=prompt, candidates_token_count=out, total_token_count=prompt + out)


def text(s: str, *, prompt_tokens: int = 100, out_tokens: int = 20) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=s)]),
                       usage_metadata=_usage(prompt_tokens, out_tokens))


def call(name: str, **args: Any) -> LlmResponse:
    part = types.Part(function_call=types.FunctionCall(name=name, args=args))
    return LlmResponse(content=types.Content(role="model", parts=[part]), usage_metadata=_usage())


class FakeLlm(BaseLlm):
    """Replays `script` one response per model call; the last step repeats when exhausted.

    `requests` keeps every LlmRequest so tests can assert on exactly what reached the model.
    """

    model: str = "fake-llm"
    _script: list[Step] = PrivateAttr(default_factory=list)
    _i: int = PrivateAttr(default=0)
    requests: list[LlmRequest] = []

    def __init__(self, script: list[Step], **kw: Any):
        super().__init__(**kw)
        self._script = list(script)
        self.requests = []

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"fake-.*"]

    async def generate_content_async(self, llm_request: LlmRequest,
                                     stream: bool = False) -> AsyncGenerator[LlmResponse]:
        self.requests.append(llm_request)
        step = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        yield step(llm_request) if callable(step) else step

    @property
    def calls(self) -> int:
        return self._i

    def prompt_texts(self) -> list[str]:
        """Every text the model saw: system instruction, contents and tool responses."""
        out = []
        for req in self.requests:
            cfg = req.config
            if cfg is not None and cfg.system_instruction:
                out.append(str(cfg.system_instruction))
            for content in req.contents or []:
                for part in content.parts or []:
                    if part.text:
                        out.append(part.text)
                    if part.function_response is not None:
                        out.append(str(part.function_response.response))
        return out


class FakeEmbedder:
    """Deterministic 16-dim vectors from word hashes: texts sharing words are close."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = []
        for t in texts:
            v = [0.0] * 16
            for w in re.findall(r"\w+", t.lower()):
                v[int(hashlib.sha256(w.encode()).hexdigest(), 16) % 16] += 1.0
            vecs.append(v)
        return vecs


_WRAPPED = re.compile(r"<untrusted source=\"[^\"]*\">.*?</untrusted>", re.S)


def assert_only_wrapped(text_: str, poison: str) -> None:
    """`poison` may appear in `text_` only inside an <untrusted> wrapper."""
    assert poison not in _WRAPPED.sub("", text_), f"unwrapped untrusted text: {poison!r}"
