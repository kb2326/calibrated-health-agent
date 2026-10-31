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


def test_decimal_on_a_ten_point_scale_is_checked_whole():
    assert unbacked("averaging 4.6 out of 10 versus 6.6 out of 10", [4.6, 6.6]) == []
    assert unbacked("averaging 7.1 out of 10", [6.6]) == ["7.1"]


def test_window_lengths_are_exempt():
    assert unbacked("the 7-day rolling average peaked at 52.3 ms", [52.3]) == []
    assert unbacked("a 14-night stretch", []) == []


def test_enumerated_and_ranged_days_are_dates():
    # found by the Phase 4 PR gate: day lists after a month were read as unbacked numbers
    answer = ("5 days have no watch data at all: October 9, 10, 11, 12, and 13, 2026 "
              "[r-4c4d9eb3e5].")
    assert unbacked(answer, [{"result": 5}]) == []
    assert unbacked("No data from Oct 9 to 13 or on Oct 20 [r-1a2b3c4d5e].", [{"n": 0}]) == []
    assert unbacked("Sept 2–6 were quiet (5 days).", [{"n": 5}]) == []


def test_a_count_after_a_date_is_still_checked():
    # no closing "and"/"or": "12" is a count, not a day, and must be backed
    assert unbacked("Since Oct 3, 12 of your nights were short.", [{"n": 4}]) == ["12"]
    assert unbacked("On October 9, 10 hours of sleep.", [{"n": 4}]) == ["10"]


def test_a_quantity_after_a_date_list_word_is_still_checked():
    # final review I9: "and 6 hours" is a quantity, not a day
    assert unbacked("You slept 7.2 hours on Oct 3 and 6 hours on Oct 4.", [{"v": 7.2}]) == ["6"]
    assert unbacked("Steps went from Oct 3 to 9 thousand a day.", [{"v": 1}]) == ["9"]
    assert unbacked("Oct 9, 10 and 11 had no data.", [{"n": 0}]) == []
