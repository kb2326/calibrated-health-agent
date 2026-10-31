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


def numbers_without_receipts(answer: str, outputs: list[Any], question: str = "") -> list[str]:
    leaves = list(_leaves(outputs)) if outputs else []
    if outputs:
        leaves = leaves[1:]  # drop the top-level list length itself
    asked = {n.rstrip("%").replace(",", "") for n in _numbers(question)}
    out = []
    for token in _numbers(answer):
        if token.rstrip("%").replace(",", "") in asked:
            continue
        if not _matches(token, leaves):
            out.append(token)
    return out
