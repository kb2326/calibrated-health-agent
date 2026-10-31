"""Binary LLM judges for what code graders cannot check, calibrated against the owner's labels.

Each judge asks one yes/no question (`evals/judges/<name>.md`); "pass" always means the good
behaviour. The transcript reaches the judge only inside an `<untrusted>` wrapper, so a poisoned
journal note or device name in a tool output can't steer the grade. Replies are JSON
`{"verdict": "pass" | "fail" | "unknown", "reason": ...}`; anything else is `unknown`. Results
are cached by (judge, prompt hash, transcript hash); a model error is `unknown` and not cached.

A judge only gates CI once `calibrate` shows TPR >= 0.8 and TNR >= 0.8 against held-out owner
labels (the test split of a 40/20/40 stratified split). Until then it is reported, not gated.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from health_agents.untrusted import UNTRUSTED_RULE, wrap

from . import stats
from .runner import Transcript

ROOT = Path("evals/judges")
JUDGES = ("answers_question", "gives_diagnosis", "admits_gap", "overrefuses")
THRESHOLD = 0.8
SEED = 20261030
Verdict = Literal["pass", "fail", "unknown"]
Model = Callable[[str], str]

_REPLY = ('Reply with JSON only: {"verdict": "pass" | "fail" | "unknown", '
          '"reason": "<one sentence>"}.')


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _transcript_text(t: Transcript) -> str:
    calls = "\n".join(f"- {c.get('name')}({json.dumps(c.get('args'), ensure_ascii=False)}) -> "
                      f"{json.dumps(c.get('response'), ensure_ascii=False, default=str)[:1500]}"
                      for c in t.tool_calls)
    return f"Question: {t.question}\n\nTool calls:\n{calls or '(none)'}\n\nReply:\n{t.answer}"


def prompt_for(name: str, t: Transcript, root: Path = ROOT) -> str:
    rubric = (Path(root) / f"{name}.md").read_text(encoding="utf-8").strip()
    return f"{rubric}\n\n{UNTRUSTED_RULE}\n\n{wrap('transcript', _transcript_text(t))}\n\n{_REPLY}"


def _default_model() -> Model:
    from google import genai
    from google.genai import types
    from health_core.settings import get_settings

    client = genai.Client()  # AI Studio free-tier key in CI (synthetic only), Vertex on laptop
    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json")

    def generate(prompt: str) -> str:
        return client.models.generate_content(model=get_settings().model_default,
                                              contents=prompt, config=config).text or ""
    return generate


def _parse(reply: str) -> tuple[Verdict, str]:
    match = re.search(r"\{.*\}", reply, re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}
    verdict = data.get("verdict") if isinstance(data, dict) else None
    reason = str(data.get("reason", "")) if isinstance(data, dict) else ""
    return (verdict if verdict in ("pass", "fail", "unknown") else "unknown"), reason  # type: ignore[return-value]


def _cache_get(cache: Path, key: str) -> Verdict | None:
    if not cache.exists():
        return None
    found = None
    for line in cache.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("key") == key:
                found = row["verdict"]
    return found


def judge(name: str, transcript: Transcript, *, model: Model | None = None, cache: Path,
          root: Path = ROOT) -> Verdict:
    if transcript.fixture_hash == "real" and model is None:
        from .runner import uses_vertex

        if not uses_vertex():
            raise ValueError("Judging real-data transcripts must use Vertex AI, never a "
                             "free-tier key")
    prompt = prompt_for(name, transcript, root)
    rubric_sha = _sha((Path(root) / f"{name}.md").read_text(encoding="utf-8"))
    key = _sha(f"{name}|{rubric_sha}|{_sha(_transcript_text(transcript))}")
    cache = Path(cache)
    hit = _cache_get(cache, key)
    if hit is not None:
        return hit
    try:
        reply = (model or _default_model())(prompt)
    except Exception:  # quota or transport: unknown, and retried next time
        return "unknown"
    verdict, reason = _parse(reply)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"key": key, "judge": name, "case_id": transcript.case_id,
                             "verdict": verdict, "reason": reason}, ensure_ascii=False) + "\n")
    return verdict


def split_labels(labels: list[dict], seed: int = SEED) -> dict[str, list]:
    """40/20/40 train/dev/test, stratified by the label's verdict and reproducible."""
    rng = random.Random(seed)
    out: dict[str, list] = {"train": [], "dev": [], "test": []}
    for verdict in sorted({x["verdict"] for x in labels}):
        group = [x for x in labels if x["verdict"] == verdict]
        rng.shuffle(group)
        n_train, n_dev = round(len(group) * 0.4), round(len(group) * 0.2)
        out["train"] += group[:n_train]
        out["dev"] += group[n_train:n_train + n_dev]
        out["test"] += group[n_train + n_dev:]
    return out


def calibrate(name: str, labelled: list[tuple[Transcript, str]], *, model: Model | None = None,
              cache: Path, root: Path = ROOT) -> dict:
    """Agreement with owner labels; an `unknown` verdict counts as a disagreement."""
    pairs = [(judge(name, t, model=model, cache=cache, root=root), human) for t, human in labelled]
    pos = [j for j, h in pairs if h == "pass"]
    neg = [j for j, h in pairs if h == "fail"]
    tp, tn = sum(j == "pass" for j in pos), sum(j == "fail" for j in neg)
    tpr = tp / len(pos) if pos else None
    tnr = tn / len(neg) if neg else None
    return {"judge": name, "n": len(pairs), "n_pass": len(pos), "n_fail": len(neg),
            "tpr": tpr, "tpr_ci": list(stats.wilson(tp, len(pos))),
            "tnr": tnr, "tnr_ci": list(stats.wilson(tn, len(neg))),
            "unknown_rate": sum(j == "unknown" for j, _ in pairs) / len(pairs) if pairs else 0.0,
            "gates": tpr is not None and tnr is not None and tpr >= THRESHOLD and tnr >= THRESHOLD}


_PAIR_REPLY = ('Reply with JSON only: {"winner": "A" | "B" | "tie", "reason": "<one sentence>"}.')


def pairwise(old: Transcript, new: Transcript, *, model: Model | None = None, cache: Path,
             root: Path = ROOT) -> str:
    """Blind A/B comparison of two answers to the same question: "old", "new", "tie" or
    "unknown". Which answer is A is decided by a hash of the question, so position bias
    averages out across questions and a rerun gives the same order."""
    rubric = (Path(root) / "pairwise.md").read_text(encoding="utf-8").strip()
    flip = int(_sha(old.question)[:2], 16) % 2 == 1
    a, b = (new, old) if flip else (old, new)
    prompt = (f"{rubric}\n\n{UNTRUSTED_RULE}\n\nQuestion: {wrap('question', old.question)}\n\n"
              f"Answer A: {wrap('answer_a', a.answer)}\n\nAnswer B: {wrap('answer_b', b.answer)}"
              f"\n\n{_PAIR_REPLY}")
    key = _sha(f"pairwise|{_sha(rubric)}|{_sha(old.answer)}|{_sha(new.answer)}|{_sha(old.question)}")
    cache = Path(cache)
    hit = _cache_get(cache, key)
    if hit is not None:
        return hit
    if (old.fixture_hash == "real" or new.fixture_hash == "real") and model is None:
        from .runner import uses_vertex

        if not uses_vertex():
            raise ValueError("Judging real-data transcripts must use Vertex AI")
    try:
        reply = (model or _default_model())(prompt)
    except Exception:
        return "unknown"
    match = re.search(r"\{.*\}", reply, re.S)
    try:
        winner = json.loads(match.group(0)).get("winner") if match else None
    except (json.JSONDecodeError, AttributeError):
        winner = None
    verdict = {"A": "new" if flip else "old", "B": "old" if flip else "new",
               "tie": "tie"}.get(str(winner), "unknown")
    if verdict != "unknown":
        cache.parent.mkdir(parents=True, exist_ok=True)
        with cache.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": key, "judge": "pairwise", "case_id": old.case_id,
                                 "verdict": verdict}) + "\n")
    return verdict
