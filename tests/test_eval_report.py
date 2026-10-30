from typing import Literal

import pytest
from health_eval import report
from health_eval.cases import Case, Expect
from health_eval.graders import Verdict
from health_eval.runner import Transcript


def _case(cid, suite="regression", category="numbers", must_pass=False):
    return Case(cid, suite, category, "q", Expect(must_pass=must_pass))


def _t(cid, trial=0, status: Literal["ok", "not_evaluated"] = "ok", reason=None, seconds=1.0,
       usd=0.001):
    return Transcript(case_id=cid, question="q", answer="a", trial=trial, status=status,
                      reason=reason, seconds=seconds, usd=usd)


def _v(ok):
    return [Verdict("x", ok, ""), Verdict("cost_latency", None, "")]


def _summary(results, cases):
    """results: {(case_id, trial): bool | None | 'quota'}"""
    transcripts, verdicts = [], {}
    for (cid, trial), r in results.items():
        if r == "quota":
            transcripts.append(_t(cid, trial, status="not_evaluated", reason="quota"))
            verdicts[(cid, trial)] = [Verdict("status", None, "not evaluated: quota")]
        else:
            transcripts.append(_t(cid, trial))
            verdicts[(cid, trial)] = _v(r)
    return report.summarise(transcripts, cases, verdicts, {})


def test_report_handles_empty_suite_and_missing_baseline(tmp_path):
    summary = report.summarise([], [], {}, {})
    assert summary["suites"] == {} and summary["latency"]["p50"] is None
    md = report.render(summary)
    assert "n = 0" in md
    ok, messages = report.gate(summary, None)
    assert ok and any("no baseline yet" in m for m in messages)
    empty_suite = report.summarise([], [_case("a")], {}, {})
    assert empty_suite["suites"]["regression"]["n"] == 0
    assert empty_suite["suites"]["regression"]["rate"] is None
    path = report.write_results(summary, out=tmp_path)
    assert path.suffix == ".md" and path.with_suffix(".json").exists()
    assert "n = 0" in report.readme_block(summary)


def test_readme_block_replaces_between_markers():
    text = "# Title\n\nintro\n<!-- scorecard:start -->\nold table\n<!-- scorecard:end -->\nafter\n"
    new = report.replace_readme_block(text, "NEW")
    assert "old table" not in new and "NEW" in new
    assert new.startswith("# Title\n\nintro\n<!-- scorecard:start -->")
    assert new.endswith("<!-- scorecard:end -->\nafter\n")
    assert report.replace_readme_block(new, "NEW") == new
    with pytest.raises(ValueError):
        report.replace_readme_block("no markers here", "x")


def test_gate_fails_on_confirmed_must_pass_failure():
    cases = [_case("m1", must_pass=True), _case("m2", must_pass=True), _case("o1")]
    summary = _summary({("m1", 0): False, ("m1", 1): False, ("m2", 0): True,
                        ("o1", 0): False}, cases)
    assert summary["must_pass_failed"] == ["m1"]
    ok, messages = report.gate(summary, None)
    assert not ok and any("m1" in m and "must-pass" in m for m in messages)


def test_gate_tolerates_flake_that_passes_retry():
    cases = [_case("m1", must_pass=True), _case("m2", must_pass=True)]
    summary = _summary({("m1", 0): False, ("m1", 1): True, ("m2", 0): True}, cases)
    assert summary["must_pass_failed"] == [] and summary["flaky"] == ["m1"]
    ok, _ = report.gate(summary, None)
    assert ok
    # the reported rate uses the first trial, so a flake still shows up in the numbers
    assert summary["suites"]["regression"]["k"] == 1 and summary["suites"]["regression"]["n"] == 2


def test_gate_fails_on_not_evaluated_with_reason():
    cases = [_case("m1", must_pass=True), _case("o1")]
    summary = _summary({("m1", 0): True, ("o1", 0): "quota"}, cases)
    assert summary["not_evaluated"] == [{"case_id": "o1", "trial": 0, "reason": "quota"}]
    ok, messages = report.gate(summary, None)
    assert not ok and any("not evaluated" in m and "quota" in m for m in messages)


def test_gate_regression_beyond_noise_band():
    cases = [_case(f"c{i}") for i in range(20)]
    base = _summary({(f"c{i}", 0): i < 18 for i in range(20)}, cases)  # 0.90
    same = _summary({(f"c{i}", 0): i < 17 for i in range(20)}, cases)  # 0.85: within 0.05
    worse = _summary({(f"c{i}", 0): i < 15 for i in range(20)}, cases)  # 0.75
    assert report.gate(same, base)[0]
    ok, messages = report.gate(worse, base)
    assert not ok and any("regression" in m and "0.90" in m and "0.75" in m for m in messages)
    base["noise_sd"] = {"regression": 0.1}  # band = max(0.05, 0.2)
    assert report.gate(worse, base)[0]


def test_summary_latency_cost_and_pass_hat_k():
    cases = [_case("a", suite="capability", category="trend"), _case("b", suite="capability")]
    transcripts = [_t("a", 0, seconds=1), _t("a", 1, seconds=3), _t("b", 0, seconds=2),
                   _t("b", 1, seconds=10)]
    verdicts = {("a", 0): _v(True), ("a", 1): _v(True), ("b", 0): _v(True), ("b", 1): _v(False)}
    s = report.summarise(transcripts, cases, verdicts, {"answers_question": {"gates": False}})
    cap = s["suites"]["capability"]
    assert cap["pass_hat_k"] == 0.5 and cap["trials"] == 2
    assert cap["categories"]["trend"]["k"] == 1
    assert s["latency"]["p50"] == pytest.approx(2.5)
    assert s["usd_per_question"] == pytest.approx(0.001)
    assert "answers_question" in report.render(s)


def test_run_suite_retries_failed_must_pass_once(tmp_path):
    from agent_fakes import FakeLlm, call, text

    count = Expect(numbers={"n": "SELECT COUNT(*) FROM journal_submissions"}, must_pass=True)
    cases = [Case("m1", "regression", "numbers", "How many journal entries?", count),
             Case("o1", "regression", "numbers", "How many journal entries?",
                  Expect(numbers=count.numbers))]
    made = []

    def factory():
        made.append(1)
        if len(made) <= 2:  # first pass: both cases answer wrongly
            return FakeLlm([text("No idea.")])
        return FakeLlm([call("run_sql", query="SELECT COUNT(*) AS n FROM journal_submissions"),
                        text("You have 41 entries.")])

    transcripts, verdicts = report.run_suite(cases, model_factory=factory, workdir=tmp_path / "w",
                                             out=tmp_path / "t.jsonl")
    assert sorted(verdicts) == [("m1", 0), ("m1", 1), ("o1", 0)]  # only the must-pass retried
    summary = report.summarise(transcripts, cases, verdicts, {})
    assert summary["flaky"] == ["m1"] and summary["must_pass_failed"] == []
    assert len((tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()) == 3
