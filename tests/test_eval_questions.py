"""The question grid: deterministic, balanced, tagged."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import yaml
from health_eval.questions import expand

GRID = yaml.safe_load(Path("evals/questions/grid.yaml").read_text(encoding="utf-8"))


def test_expand_is_deterministic():
    assert expand(GRID, 30) == expand(GRID, 30)
    assert expand(GRID, 30, seed=1) != expand(GRID, 30, seed=2)


def test_expand_balances_intents():
    items = expand(GRID, 70)
    counts = Counter(i["tags"]["intent"] for i in items)
    assert set(counts) == set(GRID["dimensions"]["intent"])
    assert max(counts.values()) - min(counts.values()) <= 1


def test_tags_are_from_the_grid():
    for item in expand(GRID, 40):
        for dim, value in item["tags"].items():
            assert value in GRID["dimensions"][dim]
        assert item["question"] and "{" not in item["question"]
        assert item["id"].startswith("q-")


def test_ids_are_unique():
    ids = [i["id"] for i in expand(GRID, 120)]
    assert len(ids) == len(set(ids))


def test_paraphrase_keeps_ids_and_tags():
    from health_eval.questions import paraphrase

    items = expand(GRID, 3)
    out = paraphrase(items, lambda prompt: "rephrased?")
    assert [o["id"] for o in out] == [i["id"] for i in items]
    assert all(o["question"] == "rephrased?" and o["template"] for o in out)
    assert [o["tags"] for o in out] == [i["tags"] for i in items]


def test_cli_writes_a_batch(tmp_path):
    from health_eval.cli import app
    from typer.testing import CliRunner

    out = tmp_path / "batch.yaml"
    result = CliRunner().invoke(app, ["questions", "--n", "7", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert len(yaml.safe_load(out.read_text(encoding="utf-8"))["questions"]) == 7
