"""A plain-language line for a receipt: what the code read, before the code itself."""
from __future__ import annotations

import re

TABLES = {
    "sleep_sessions": "sleep sessions",
    "exercise_sessions": "workouts",
    "night_vitals": "night vitals",
    "activity_breakdown": "activity zones",
    "hr_zone_thresholds": "heart-rate zones",
    "weather_daily": "weather",
    "journal_submissions": "journal",
    "raw_points": "raw readings",
    "daily_metrics": "daily metrics",
}
FRAMES = {**TABLES, "days": "days", "journal": "journal", "metrics": "daily metrics"}
_DATA_TYPE = re.compile(r"data_type\s*=\s*'([a-z0-9-]+)'")


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def describe_receipt(kind: str, code: str) -> str:
    text = code or ""
    if kind == "sql":
        found = sorted((m.start(), t) for t in TABLES for m in re.finditer(rf"\b{t}\b", text))
        names = list(dict.fromkeys(t for _, t in found))
        if names == ["daily_metrics"]:
            types = list(dict.fromkeys(_DATA_TYPE.findall(text)))
            if types:
                return "SQL over " + _join(
                    ["daily " + t.removeprefix("daily-").replace("-", " ") for t in types])
        if names:
            return "SQL over your " + _join([TABLES[n] for n in names])
        return "SQL query"
    found = sorted((m.start(), f) for f in FRAMES
                   for m in re.finditer(rf"""frames\[\s*['"]{f}['"]\s*\]""", text))
    names = list(dict.fromkeys(f for _, f in found))
    if names:
        return "Python over your " + _join([FRAMES[n] for n in names])
    return "Python computation"
