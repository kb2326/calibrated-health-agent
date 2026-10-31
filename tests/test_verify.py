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


def test_window_phrases_are_backed():
    # owner labelling: "unverified: 30" on a correct answer to "last month"
    assert unbacked("Over the last 30 days your RHR averaged 61.5 [r-1a2b3c4d5e].", [{"m": 61.5}],
                    "what was my average resting heart rate over the last month?") == []
    assert unbacked("Across the past 7 days you slept 6.8 h.", [{"h": 6.8}], "how did I sleep this week?") == []
    assert unbacked("In the last 14 days: 9,378 steps a day.", [{"s": 9378}], "steps the past two weeks?") == []


def test_day_counts_between_dates_are_backed():
    answer = "From 2026-10-01 to 2026-10-30 (30 days) you averaged 61.5 [r-1a2b3c4d5e]."
    assert unbacked(answer, [{"m": 61.5}]) == []
    assert unbacked("From 2026-10-01 to 2026-10-30 you had 12 rest days.", [{"m": 1}]) == ["12"]


def test_quiet_note_round_trip():
    from health_agents.verify import note, unbacked_in

    assert unbacked_in("All good.") == []
    text_ = "Answer 9.9." + note(["9.9"])
    assert unbacked_in(text_) == ["9.9"] and "unverified:" not in text_
    assert unbacked_in("Answer." + note(["3", "12"])) == ["3", "12"]
    assert unbacked_in("old\n\nunverified: 4, 5") == ["4", "5"]  # older transcripts still read


def test_a_window_number_is_backed_only_as_a_time_span():
    assert unbacked("You slept 7 hours a night this week.", [{"x": 6.1}], "how did I sleep this week?") == ["7"]


# Review I3 / I4: the window exemption must not wave through counts of days meeting a
# condition, and data_catalog coverage numbers must not back health values.
def test_count_of_nights_meeting_a_condition_is_checked():
    from health_agents.verify import numbers_without_receipts as nwr

    assert nwr("You slept under 7 hours on 6 nights.", [{"x": 7}], "How did I sleep last week?") \
        == ["6"]
    assert nwr("Between 2026-10-01 and 2026-10-12 your HRV dipped on 11 days.", [{"x": 1}]) \
        == ["11"]


def test_only_the_stated_window_span_is_implied():
    from health_agents.verify import numbers_without_receipts as nwr

    # first and last date only: 2026-10-05 to 2026-10-12 is not a window the answer stated
    ans = "From 2026-10-01 to 2026-10-30 (30 days), best was 2026-10-05, worst 2026-10-12: 7 days apart."
    assert nwr(ans, [{"x": 1}]) == ["7"]
    assert nwr("Over the last 30 days your average was 61 bpm.", [{"avg": 61}],
               "last month resting heart rate?") == []


def test_catalog_coverage_backs_day_counts_not_values():
    from health_agents.verify import numbers_without_receipts as nwr

    catalog = {"metrics": [{"name": "resting_heart_rate", "days": 58, "days_last_30": 29}],
               "tables": [], "as_of": "2026-10-30", "note": "x"}
    assert nwr("Your resting heart rate was 58 bpm.", [catalog]) == ["58"]
    assert nwr("You have 58 days of resting heart rate data.", [catalog]) == []
