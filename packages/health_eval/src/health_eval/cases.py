"""Eval cases: YAML under `evals/cases/` is the source of truth.

Each case carries what ADK's evalset format can't: its suite, the failure category it tests,
fixture-computed truth (a read-only SQL query per expected number) and expected behaviours.
`to_evalset` generates the ADK `EvalSet` JSON from the same cases, so `adk eval` and
`AgentEvaluator` metrics (tool trajectory, safety, hallucination) run on identical questions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

BEHAVIOURS = ("admits_gap", "refuses_diagnosis", "escalates_care", "no_overrefusal",
              "no_unverified", "cites_receipt", "resists_injection")
SUITES = ("regression", "capability", "safety", "redteam", "ablation")
ROOT = Path("evals/cases")


@dataclass(frozen=True)
class Expect:
    numbers: dict[str, str] = field(default_factory=dict)  # label -> truth SQL on the fixture
    tools_any: list[str] = field(default_factory=list)
    tools_none: list[str] = field(default_factory=list)
    behaviour: list[str] = field(default_factory=list)
    must_pass: bool = False


@dataclass(frozen=True)
class Case:
    id: str
    suite: str
    category: str
    question: str | list[str]
    expect: Expect = field(default_factory=Expect)

    @property
    def turns(self) -> list[str]:
        return [self.question] if isinstance(self.question, str) else list(self.question)


def _case(raw: dict, suite: str) -> Case:
    for key in ("id", "category", "question"):
        if not raw.get(key):
            raise ValueError(f"case {raw.get('id', '?')}: missing {key}")
    exp = raw.get("expect") or {}
    unknown = set(exp.get("behaviour", [])) - set(BEHAVIOURS)
    if unknown:
        raise ValueError(f"case {raw['id']}: unknown behaviour {sorted(unknown)}")
    return Case(id=str(raw["id"]), suite=suite, category=str(raw["category"]),
                question=raw["question"],
                expect=Expect(numbers=dict(exp.get("numbers", {})),
                              tools_any=list(exp.get("tools_any", [])),
                              tools_none=list(exp.get("tools_none", [])),
                              behaviour=list(exp.get("behaviour", [])),
                              must_pass=bool(exp.get("must_pass", False))))


def load_cases(suite: str, root: Path = ROOT) -> list[Case]:
    data = yaml.safe_load((Path(root) / f"{suite}.yaml").read_text(encoding="utf-8")) or {}
    cases = [_case(raw, suite) for raw in data.get("cases", [])]
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise ValueError(f"duplicate case id {case.id} in {suite}")
        seen.add(case.id)
    return cases


def to_evalset(cases: list[Case], suite: str) -> dict:
    """ADK EvalSet JSON for `cases` (validated through ADK's own models)."""
    from google.adk.evaluation.eval_set import EvalSet

    eval_cases = []
    for case in cases:
        conversation = []
        for i, turn in enumerate(case.turns):
            # ADK's trajectory metric needs every expected tool; `tools_any` means one of
            # them, so only a single named tool becomes an expected tool use.
            single = len(case.expect.tools_any) == 1 and i == len(case.turns) - 1
            tool_uses = [{"name": case.expect.tools_any[0], "args": {}}] if single else []
            conversation.append({
                "invocation_id": f"{case.id}-{i}",
                "user_content": {"role": "user", "parts": [{"text": turn}]},
                "intermediate_data": {"tool_uses": tool_uses},
            })
        eval_cases.append({"eval_id": case.id, "conversation": conversation})
    data = {"eval_set_id": suite, "name": suite,
            "description": f"Generated from evals/cases/{suite}.yaml", "eval_cases": eval_cases}
    return EvalSet.model_validate(data).model_dump(mode="json", exclude_none=True)


def write_evalsets(root: Path = ROOT, out: Path = Path("evals/generated")) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for suite in SUITES:
        if (Path(root) / f"{suite}.yaml").exists():
            path = out / f"{suite}.evalset.json"
            path.write_text(json.dumps(to_evalset(load_cases(suite, root), suite), indent=1) + "\n",
                            encoding="utf-8")
            written.append(path)
    return written
