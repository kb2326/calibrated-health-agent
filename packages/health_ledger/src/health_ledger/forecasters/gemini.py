"""Forecaster 6: Gemini on Vertex AI, betting from the same snapshot as everyone else.

One `generate_content` call per locked day returns all three distributions. It runs with
the job's service account (no API key), temperature 0, JSON output, and the model pinned
in `Settings.forecast_model`. The stored forecaster name includes the model
(`gemini:<model>`), so a model change is scored as a new forecaster.

Fairness: the prompt holds fixed instructions plus the canonical snapshot restricted to
`features.KEYS`, nothing else (no journal note text, no other forecaster's bet). Any
failure (error, invalid JSON, a missing target, wrong length, negative values, a sum
outside 0.9..1.1) abstains all three targets with a reason that carries no values.

Cost: Flash-Lite, about 1-2k tokens a day, well under a cent a month.

`python -m health_ledger.forecasters.gemini --selftest` sends one synthetic snapshot to
the configured model (owner credentials) to prove the model ID is served.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from datetime import date
from typing import Any

from health_core.settings import get_settings

from health_ledger import dist, features
from health_ledger.forecasters.base import TARGETS, Forecast

FORECASTER_ID = f"gemini:{get_settings().forecast_model}"
TIMEOUT_MS = 60_000  # a hung call abstains instead of holding the job to its 15-min limit

INSTRUCTIONS = """You forecast how one person will rate their own day this evening.
They rate mood, energy and soreness on a 1-10 scale (10 = excellent mood, full of energy,
very sore). Below is everything known at this morning's lock, as JSON: last night's sleep
minutes, Fitbit HRV (RMSSD, ms), resting heart rate (bpm), an open readiness score (50 =
a usual morning, higher = more recovered), yesterday's steps, and recent journal ratings.
null means the value is missing. This is wellness forecasting, not medical advice.

Return JSON with keys "mood", "energy" and "soreness", each an array of exactly 10
probabilities for the scores 1..10 (first number = score 1) that sum to 1. Be calibrated:
spread probability when the data says little.

Data:
"""


class _Invalid(ValueError):
    """The model's output could not be used; the message carries no values."""


def _client() -> Any:
    from google import genai
    from google.genai import types

    settings = get_settings()
    return genai.Client(vertexai=True, project=settings.gcp_project,
                        location=settings.vertex_location,
                        http_options=types.HttpOptions(timeout=TIMEOUT_MS))


def _config() -> Any:
    from google.genai import types

    array10 = {"type": "ARRAY", "items": {"type": "NUMBER"}, "minItems": 10, "maxItems": 10}
    return types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
        response_schema={"type": "OBJECT", "properties": dict.fromkeys(TARGETS, array10),
                         "required": list(TARGETS)},
    )


def prompt(snapshot: dict) -> str:
    return INSTRUCTIONS + features.canonical({k: snapshot.get(k) for k in features.KEYS})


def _parse(text: str) -> dict[str, dist.Dist]:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise _Invalid("invalid JSON") from None
    if not isinstance(data, dict):
        raise _Invalid("invalid JSON")
    probs = {}
    for target in TARGETS:
        values = data.get(target)
        if not isinstance(values, list):
            raise _Invalid("missing target")
        if len(values) != dist.K:
            raise _Invalid(f"need {dist.K} probabilities")
        if not all(isinstance(v, int | float) and math.isfinite(v) and v >= 0 for v in values):
            raise _Invalid("invalid probabilities")
        if not 0.9 <= sum(values) <= 1.1:
            raise _Invalid("probabilities do not sum to 1")
        probs[target] = dist.normalize(values)
    return probs


def forecast(conn: sqlite3.Connection, day: date, snapshot: dict, *, client: Any = None) -> Forecast:
    try:
        client = client or _client()
        response = client.models.generate_content(
            model=get_settings().forecast_model, contents=prompt(snapshot), config=_config())
        return Forecast(probs=_parse(response.text))
    except _Invalid as exc:
        return Forecast.abstain_all(f"gemini: {exc}")
    except Exception as exc:  # never keep the message: it may echo the prompt
        return Forecast.abstain_all(f"gemini: {type(exc).__name__}")


def _selftest() -> int:
    snap = {"day": "2026-01-15", "weekday": 3, "sleep_minutes": 430.0, "hrv_rmssd": 42.0,
            "resting_hr": 61.0, "readiness": 55.0, "steps_prev_day": 6000.0,
            "journal_prev_day": {"mood": 6, "energy": 6, "soreness": 3},
            "journal_last7": {"mood": [6], "energy": [6], "soreness": [3]},
            "journal_days_total": 1}
    result = forecast(None, date(2026, 1, 15), snap)  # type: ignore[arg-type]
    print(FORECASTER_ID, "abstain:" if result.abstain else "ok", result.abstain or "")
    return 1 if result.abstain else 0


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else 2)
