"""verify_receipts' matcher: every number in an answer must come from this turn's tool outputs."""
from __future__ import annotations

from health_agents.verify import numbers_without_receipts as unbacked


def test_backed_number_passes():
    assert unbacked("Mean 6.4 (n=12)", [{"result": 6.4, "n": 12}]) == []


def test_unbacked_number_is_reported():
    assert unbacked("Mean 7.9", [{"result": 6.4}]) == ["7.9"]


def test_dates_and_receipt_ids_exempt():
    assert unbacked("On 2026-10-20 it was 6.4 [r-1a2b3c4d5e]; since Oct 3 too", [6.4]) == []


def test_rounding_to_answer_precision():
    assert unbacked("about 6.4 hours", [{"x": 6.4321}]) == []
    assert unbacked("about 6 hours", [{"x": 6.4321}]) == []
    assert unbacked("about 6.5 hours", [{"x": 6.4321}]) == ["6.5"]


def test_percent_from_a_fraction():
    assert unbacked("up 12%", [{"change": 0.12}]) == []
    assert unbacked("up 12.5%", [{"change_pct": 12.5}]) == []


def test_counts_of_returned_rows_are_backed():
    assert unbacked("over 3 days", [{"rows": [{}, {}, {}]}]) == []


def test_numbers_from_the_question_are_exempt():
    assert unbacked("In the last 30 days: 6.4", [6.4], question="last 30 days?") == []


def test_scale_and_list_markers_exempt():
    assert unbacked("1. Energy was 6 out of 10\n2. Fine", [6]) == []


def test_thousands_separators():
    assert unbacked("You walked 10,432 steps", [{"steps": 10432}]) == []


def test_no_outputs_means_every_number_is_unbacked():
    assert unbacked("Mean 6.4 over 12 days", []) == ["6.4", "12"]


def test_years_and_written_dates_exempt():
    assert unbacked("From August 24, 2026 to Oct 22, 2026 sleep averaged 6.9 h", [6.9]) == []
    assert unbacked("In 2026 you slept 6.9 h", [6.9]) == []


def test_times_and_ordinals_exempt():
    assert unbacked("On the 3rd, at 22:30, it was 6.9", [6.9]) == []


def test_week_numbers_are_not_exempt_without_output():
    assert unbacked("week 41 averaged 50.2", [50.2]) == ["41"]


def test_a_bare_number_that_looks_like_a_year_still_needs_backing():
    assert unbacked("You burned 1950 kcal", [6.9]) == ["1950"]
