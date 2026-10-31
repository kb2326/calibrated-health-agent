"""A scripted stand-in model for the end-to-end browser test (demo mode only).

The script is a JSON list of turns. Each turn matches the person's latest question (a
case-insensitive substring) and lists the model's responses in order; the step used is the
number of tool results the agent has seen since that question:
  [{"match": "resting heart rate",
    "steps": [{"call": "run_sql", "args": {...}},
              {"text": "... [{receipt}]"}]}]
{receipt} becomes the newest receipt id among those tool results. No network and no
credentials; `cha-web` accepts it only with --demo.
"""
from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import PrivateAttr

RECEIPT = re.compile(r"r-[0-9a-f]{10}")
FALLBACK = "I don't have a scripted answer for that question."


def _usage() -> types.GenerateContentResponseUsageMetadata:
    return types.GenerateContentResponseUsageMetadata(prompt_token_count=100, candidates_token_count=20,
                                                      total_token_count=120)


def _since_question(req: LlmRequest) -> tuple[str, list[Any]]:
    """The latest user text and the tool results that came after it."""
    question, responses = "", []
    for content in req.contents or []:
        for part in content.parts or []:
            if content.role == "user" and part.text:
                question, responses = part.text, []
            elif part.function_response is not None:
                responses.append(part.function_response.response)
    return question, responses


class ScriptedLlm(BaseLlm):
    model: str = "scripted-e2e"
    _turns: list[dict[str, Any]] = PrivateAttr(default_factory=list)

    def __init__(self, turns: list[dict[str, Any]], **kw: Any):
        super().__init__(**kw)
        if not turns or not all(t.get("steps") for t in turns):
            raise ValueError("each scripted turn needs a match and at least one step")
        self._turns = turns

    @classmethod
    def from_file(cls, path: str | Path) -> ScriptedLlm:
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"scripted-.*"]

    async def generate_content_async(self, llm_request: LlmRequest,
                                     stream: bool = False) -> AsyncGenerator[LlmResponse]:
        question, responses = _since_question(llm_request)
        turn = next((t for t in self._turns if str(t.get("match", "")).lower() in question.lower()), None)
        if turn is None:
            part = types.Part(text=FALLBACK)
        else:
            steps = turn["steps"]
            step = steps[min(len(responses), len(steps) - 1)]
            if "call" in step:
                part = types.Part(function_call=types.FunctionCall(name=step["call"], args=step.get("args", {})))
            else:
                ids = RECEIPT.findall(json.dumps(responses, default=str))
                part = types.Part(text=str(step.get("text", "")).replace("{receipt}", ids[-1] if ids else ""))
        yield LlmResponse(content=types.Content(role="model", parts=[part]), usage_metadata=_usage())
