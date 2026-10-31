from collections import Counter

import pytest
from health_eval import fixture
from health_eval.cases import BEHAVIOURS, SUITES, load_cases

TARGETS = {"regression": (40, 50), "capability": (70, 90), "safety": (25, 35),
           "redteam": (35, 45), "ablation": (55, 65)}


def test_suites_meet_targets_and_validate():
    covered: set[str] = set()
    for suite in SUITES:
        cases = load_cases(suite)
        lo, hi = TARGETS[suite]
        assert lo <= len(cases) <= hi, (suite, len(cases))
        assert all(c.category for c in cases)
        for c in cases:
            covered.update(c.expect.behaviour)
    assert sum(c.expect.must_pass for c in load_cases("regression")) >= 20
    safety = load_cases("safety")
    negatives = [c for c in safety if "no_overrefusal" in c.expect.behaviour]
    assert len(negatives) / len(safety) >= 0.3
    assert all(c.expect.numbers for c in load_cases("ablation"))
    assert covered >= set(BEHAVIOURS), set(BEHAVIOURS) - covered
    ids = Counter(c.id for s in SUITES for c in load_cases(s))
    assert not [i for i, n in ids.items() if n > 1]


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return fixture.build(tmp_path_factory.mktemp("suites") / "health.db")


def test_truth_queries_run_on_fixture(db):
    for suite in SUITES:
        for case in load_cases(suite):
            for label, sql in case.expect.numbers.items():
                value = fixture.truth(db, sql)
                assert value is not None, (case.id, label)
                float(value)


def test_expected_tools_exist():
    from health_agents.workflow import ALL_TOOLS

    real = {getattr(t, "name", getattr(t, "__name__", "")) for t in ALL_TOOLS}
    used = {n for s in SUITES for c in load_cases(s)
            for n in c.expect.tools_any + c.expect.tools_none}
    assert used <= real, used - real
