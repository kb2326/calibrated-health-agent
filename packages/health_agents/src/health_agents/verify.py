"""Find numbers in an answer that no tool output of this turn produced.

A number is backed when it equals, at the answer's own precision, a numeric value (or a
row count) somewhere in this turn's tool outputs, or that value times 100 for a
percentage. Exempt: receipt ids, ISO dates, written dates ("Oct 3", "August 24, 2026"),
years, clock times, ordinals ("the 3rd"), window lengths ("7-day"), ordered-list markers, "out of 10" scales, and
numbers the question itself contained ("last 30 days").
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_RECEIPT = re.compile(r"\br-[0-9a-f]{10}\b")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+Z?)?\b")
_MONTH_DAY = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
                        r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?\b")
# "October 9, 10, 11, 12, and 13, 2026" / "Oct 9 to 13" / "Sept 2–6": the extra numbers are
# days only when the list is closed by and/or, or is a range. Without that ("Oct 3, 12 of
# your nights") the number after the date stays a number and must be backed.
# A trailing number followed by a unit is a quantity ("Oct 3 and 6 hours"), never a day.
_DAY = r"\d{1,2}(?:st|nd|rd|th)?"
_NOT_A_QUANTITY = (r"(?!\.\d|\d|\s*(?:hours?|hrs?|h\b|minutes?|mins?|steps?|bpm|ms\b|thousand"
                   r"|k\b|km|kg|%|percent|nights?|days?|times?)\b)")
_MONTH_DAY_LIST = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+" + _DAY
    + r"(?:(?:\s*,\s*" + _DAY + r")*\s*,?\s+(?:and|or)\s+" + _DAY + _NOT_A_QUANTITY
    + r"|\s*(?:–|-|to|through)\s*" + _DAY + _NOT_A_QUANTITY + r")(?:,?\s+\d{4})?\b")
_YEAR = re.compile(r"(?i)\b(?:in|of|since|year|by)\s+(?:19|20)\d{2}\b")
_TIME = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_ORDINAL = re.compile(r"\b\d+(?:st|nd|rd|th)\b")
_WINDOW = re.compile(r"\b\d+-(?:day|week|month|night|hour)s?\b", re.I)
_LIST_MARKER = re.compile(r"(?m)^\s*\d+[.)]\s")
_SCALE = re.compile(r"(?:out of|/)\s*10\b|\b1\s*[–-]\s*10\b")  # the value before it is checked
_NUMBER = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|(?<![\w.])-?\d+(?:\.\d+)?%?")


def _leaves(value: Any) -> Iterable[float]:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, str):
        try:
            yield float(value)
        except ValueError:
            return
    elif isinstance(value, dict):
        for v in value.values():
            yield from _leaves(v)
    elif isinstance(value, (list, tuple)):
        yield float(len(value))
        for v in value:
            yield from _leaves(v)


def _strip(text: str) -> str:
    for pattern in (_RECEIPT, _DATE, _MONTH_DAY_LIST, _MONTH_DAY, _TIME, _ORDINAL, _WINDOW, _YEAR, _LIST_MARKER, _SCALE):
        text = pattern.sub(" ", text)
    return text


def _numbers(text: str) -> list[str]:
    return _NUMBER.findall(_strip(text))


def _matches(token: str, leaves: list[float]) -> bool:
    pct = token.endswith("%")
    raw = token.rstrip("%").replace(",", "")
    value = float(raw)
    places = len(raw.split(".")[1]) if "." in raw else 0
    candidates = leaves + [x * 100 for x in leaves] if pct else leaves
    tol = 0.5 * 10 ** -places + 1e-9
    return any(abs(x - value) <= tol for x in candidates)


# Numbers a reader supplies from the question's wording ("last month" -> 30) or from dates
# the answer states (2026-10-01 to 2026-10-30 -> 30 days). The owner's labelling showed a
# correct answer flagged "unverified: 30" for "last month": that is arithmetic about the
# window, not a health figure.
_WINDOWS = (
    # A bare "7 days" in the answer is not a window by itself ("7 days apart"); it needs a
    # window word before it.
    (re.compile(r"\b(?:this|last|past|previous)\s+(?:week|7 days)\b|\bweekly\b", re.I), (7,)),
    (re.compile(r"\bfortnight\b|\btwo weeks\b|\b2 weeks\b", re.I), (14,)),
    (re.compile(r"\b(?:this|last|past|previous)\s+(?:month|30 days)\b|\bmonthly\b", re.I),
     (28, 29, 30, 31)),
    (re.compile(r"\bquarter\b|\b3 months\b|\bthree months\b", re.I), (90, 91, 92)),
    (re.compile(r"\b(?:this|last|past|previous)\s+year\b|\b12 months\b", re.I), (365, 366, 12)),
)
_ISO_DAY = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _implied(answer: str, question: str) -> set[float]:
    from datetime import date

    out: set[float] = set()
    text = f"{question}\n{answer}"
    for pattern, values in _WINDOWS:
        if pattern.search(text):
            out.update(float(v) for v in values)
    days = []
    for d in _ISO_DAY.findall(answer):
        try:
            days.append(date.fromisoformat(d))
        except ValueError:
            continue
    if len(days) >= 2:  # the window the answer states: its first and last date only
        span = abs((max(days) - min(days)).days)
        out.update((float(span), float(span + 1)))
    return out


# "on 6 nights", "of 11 days", "had 4 days": a count of days meeting a condition is a health
# figure, never the window, so it is not exempt.
_CONDITION_BEFORE = re.compile(
    r"(?:\bon|\bof|\bhad|\bwith|\bwere|\bwas|\bjust|\bonly)\s+$", re.I)


def _is_span(token: str, answer: str) -> bool:
    """The token is followed by a time unit and not preceded by a condition word."""
    return any(not _CONDITION_BEFORE.search(answer[:m.start()])
               for m in _SPAN_AFTER(token).finditer(answer))


def _is_catalog(output: Any) -> bool:
    return isinstance(output, dict) and {"metrics", "tables", "as_of"} <= output.keys()


def numbers_without_receipts(answer: str, outputs: list[Any], question: str = "") -> list[str]:
    # data_catalog says how many days each metric covers: those numbers back a day count
    # ("58 days of data"), never a health value ("58 bpm").
    values = [o for o in outputs or [] if not _is_catalog(o)]
    leaves = list(_leaves(values))[1:]  # drop the top-level list length itself
    coverage = [x for o in outputs or [] if _is_catalog(o) for x in _leaves(o)]
    implied = sorted(_implied(answer, question))
    asked = {n.rstrip("%").replace(",", "") for n in _numbers(question)}
    out = []
    for token in _numbers(answer):
        if token.rstrip("%").replace(",", "") in asked:
            continue
        if _matches(token, leaves):
            continue
        if _matches(token, implied + coverage) and _is_span(token, answer):
            continue  # "30 days": the window or the coverage, not a health figure
        out.append(token)
    return out


def _SPAN_AFTER(token: str) -> re.Pattern[str]:  # noqa: N802 (reads as a pattern constant)
    return re.compile(r"(?<![\w.])" + re.escape(token) + r"\s*(?:recorded\s+|calendar\s+)?"
                      r"(?:days?|nights?|weeks?|months?|years?)(?![a-z])", re.I)



# The quiet note appended when a number stays unbacked after one revision. It replaces the
# old "unverified: ..." footer, which read like an error; both forms are still parsed.
_NOTE = re.compile(r"_Note: \d+ figures? (?:wasn't|weren't) computed by a tool: (.+?)\._\s*$")
_FOOTER = re.compile(r"\n\nunverified: (.+?)\s*$")


def note(unbacked: list[str]) -> str:
    if not unbacked:
        return ""
    n = len(unbacked)
    verb = "figure wasn't" if n == 1 else "figures weren't"
    return f"\n\n_Note: {n} {verb} computed by a tool: {', '.join(unbacked)}._"


def unbacked_in(answer: str) -> list[str]:
    """The numbers an answer itself flags as not computed (note or legacy footer)."""
    for pattern in (_NOTE, _FOOTER):
        m = pattern.search(answer or "")
        if m:
            return [x.strip() for x in m.group(1).split(",") if x.strip()]
    return []
