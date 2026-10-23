"""Forecaster 6: Gemini on Vertex AI, given exactly the shared snapshot (fake client)."""
from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest
from health_ledger import dist, forecasters
from health_ledger.forecasters import gemini

D = date(2026, 10, 30)
TARGETS = ("mood", "energy", "soreness")
SNAP = {"day": "2026-10-30", "weekday": 4, "sleep_minutes": 420.0, "readiness": 61.0,
        "journal_prev_day": {"mood": 6, "energy": 5, "soreness": 2}}


class FakeModels:
    def __init__(self, text: str | None = None, error: Exception | None = None):
        self.text, self.error, self.calls = text, error, []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text)


def _client(text=None, error=None):
    return SimpleNamespace(models=FakeModels(text, error))


def _good() -> str:
    p = [0.0, 0.0, 0.05, 0.1, 0.2, 0.3, 0.2, 0.1, 0.05, 0.0]
    return json.dumps({t: p for t in TARGETS})


def test_registered_under_model_scoped_id():
    assert gemini.FORECASTER_ID == f"gemini:{gemini.get_settings().forecast_model}"
    assert list(forecasters.FORECASTERS)[-1] == gemini.FORECASTER_ID
    assert list(forecasters.FORECASTERS).index("timesfm") == len(forecasters.FORECASTERS) - 2


def test_gemini_parses_three_distributions():
    client = _client(_good())
    f = gemini.forecast(None, D, SNAP, client=client)  # type: ignore[arg-type]
    assert f.abstain == {} and set(f.probs) == set(TARGETS)
    assert f.probs["energy"] == pytest.approx(dist.normalize(json.loads(_good())["energy"]))
    call = client.models.calls[0]
    assert call["config"].temperature == 0
    assert call["config"].response_mime_type == "application/json"
    assert call["model"] == gemini.get_settings().forecast_model


@pytest.mark.parametrize("text, reason", [
    (json.dumps({t: [0.3] * 10 for t in TARGETS}), "probabilities do not sum to 1"),
    (json.dumps({t: [0.1] * 9 for t in TARGETS}), "need 10 probabilities"),
    ("not json", "invalid JSON"),
    (json.dumps({"mood": [0.1] * 10}), "missing target"),
    (json.dumps({t: [-0.1] + [0.11] * 9 for t in TARGETS}), "invalid probabilities"),
])
def test_gemini_bad_output_abstains(text, reason):
    f = gemini.forecast(None, D, SNAP, client=_client(text))  # type: ignore[arg-type]
    assert f.probs == {} and set(f.abstain) == set(TARGETS)
    assert f.abstain["mood"].startswith("gemini: ") and reason in f.abstain["mood"]


def test_gemini_error_abstains_with_type_only():
    f = gemini.forecast(None, D, SNAP, client=_client(error=RuntimeError("energy was 3")))  # type: ignore[arg-type]
    assert f.abstain["energy"] == "gemini: RuntimeError"


def test_gemini_prompt_contains_snapshot_only():
    client = _client(_good())
    gemini.forecast(None, D, {**SNAP, "note": "private text"}, client=client)  # type: ignore[arg-type]
    prompt = client.models.calls[0]["contents"]
    assert '"sleep_minutes":420.0' in prompt and '"readiness":61.0' in prompt
    assert "private text" not in prompt and "note" not in prompt
    assert "climatology" not in prompt and "persistence" not in prompt  # no other bets
