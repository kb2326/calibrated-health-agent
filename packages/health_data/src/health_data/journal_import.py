"""Import journal submissions straight from the Google Forms API (no Sheet).

Answers are mapped to fields by question *title*, every submission is appended
(never overwritten), and problems are recorded with a reason - never with the
answer values.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from health_core.settings import get_settings
from pydantic import BaseModel, model_validator

from health_data.db import utc_stamp

SCOPE = "https://www.googleapis.com/auth/forms.responses.readonly"
SCORES = (("Mood", "mood"), ("Energy", "energy"), ("Soreness", "soreness"))


class JournalRow(BaseModel):
    response_id: str
    date: date
    mood: int | None
    energy: int | None
    soreness: int | None
    note: str | None = None
    tags: list[str] = []
    submitted_at: datetime  # response createTime, UTC
    last_submitted_at: datetime  # response lastSubmittedTime, UTC
    status: Literal["ok", "late", "invalid"] = "ok"
    reason: str | None = None

    @model_validator(mode="after")
    def _scores_in_range(self) -> JournalRow:
        if self.status != "invalid":
            for name in ("mood", "energy", "soreness"):
                value = getattr(self, name)
                if value is None or not 1 <= value <= 10:
                    raise ValueError(f"{name} must be 1..10 unless the row is invalid")
        return self


def _forms_service() -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    path = get_settings().forms_token_path
    creds = Credentials.from_authorized_user_file(str(path), [SCOPE])  # type: ignore[no-untyped-call]
    if not creds.valid:
        creds.refresh(Request())
        path.write_text(creds.to_json())
    return build("forms", "v1", credentials=creds, cache_discovery=False)


def fetch_responses(form_id: str) -> tuple[dict[str, str], list[dict]]:
    """Return ({question title: questionId}, all responses) for the Form."""
    forms = _forms_service()
    form = forms.forms().get(formId=form_id).execute()
    question_ids = {
        item["title"]: item["questionItem"]["question"]["questionId"]
        for item in form.get("items", [])
        if "questionItem" in item and "title" in item
    }
    responses: list[dict] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"formId": form_id}
        if token:
            kwargs["pageToken"] = token
        page = forms.forms().responses().list(**kwargs).execute()
        responses.extend(page.get("responses", []))
        token = page.get("nextPageToken")
        if not token:
            return question_ids, responses


def _utc(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)


def _answers(response: dict, question_id: str | None) -> list[str]:
    if question_id is None:
        return []
    block = response.get("answers", {}).get(question_id, {})
    return [a["value"] for a in block.get("textAnswers", {}).get("answers", []) if "value" in a]


def _int_or_none(raw: str | None) -> int | None:
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


def parse_responses(
    question_ids: dict[str, str], responses: list[dict], tz: str,
) -> tuple[list[JournalRow], list[str]]:
    """Turn raw Forms responses into rows; problems are listed without answer values."""
    zone = ZoneInfo(tz)
    rows: list[JournalRow] = []
    problems: list[str] = []
    for resp in responses:
        rid = resp["responseId"]
        created = _utc(resp["createTime"])
        last = _utc(resp.get("lastSubmittedTime", resp["createTime"]))
        reasons: list[str] = []

        def one(title: str, resp: dict = resp) -> str | None:
            vals = _answers(resp, question_ids.get(title))
            return vals[0] if vals else None

        day: date | None = None
        raw_day = one("Date")
        if raw_day is None:
            reasons.append("missing required answer: date")
        else:
            try:
                day = date.fromisoformat(raw_day)
            except ValueError:
                reasons.append("unparseable date")
        scores: dict[str, int | None] = {}
        for title, field in SCORES:
            raw = one(title)
            value = _int_or_none(raw)
            if raw is None:
                reasons.append(f"missing required answer: {field}")
            elif value is None or not 1 <= value <= 10:
                reasons.append(f"{field} out of range 1..10")
            scores[field] = value
        status: Literal["ok", "late", "invalid"] = "invalid" if reasons else "ok"
        if day is None:
            day = created.astimezone(zone).date()  # best guess; the row is invalid anyway
        elif day > created.astimezone(zone).date():
            status = "invalid"
            reasons.append("date after submission")
        elif status == "ok":
            deadline = datetime.combine(day + timedelta(days=1), time(6), tzinfo=zone)
            if created > deadline:
                status = "late"
                reasons.append("submitted after D+1 06:00 in the owner time zone")
        rows.append(JournalRow(
            response_id=rid, date=day, mood=scores["mood"], energy=scores["energy"],
            soreness=scores["soreness"], note=one("Note") or None,
            tags=_answers(resp, question_ids.get("Tags")), submitted_at=created,
            last_submitted_at=last, status=status,
            reason="; ".join(reasons) if reasons else None,
        ))
        if status == "invalid":
            problems.append(f"{rid}: {'; '.join(reasons)}")
    return rows, problems


def _row_hash(row: JournalRow) -> str:
    payload = json.dumps([
        row.response_id, utc_stamp(row.last_submitted_at), row.date.isoformat(),
        row.mood, row.energy, row.soreness, row.note or "", sorted(row.tags),
    ], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def append_submissions(conn: sqlite3.Connection, rows: list[JournalRow]) -> dict[str, int]:
    """Append new submissions; return counts by stored status. Known hashes are skipped."""
    counts: dict[str, int] = {}
    imported = utc_stamp()
    for row in rows:
        digest = _row_hash(row)
        if conn.execute(
            "SELECT 1 FROM journal_submissions WHERE row_hash=?", (digest,)
        ).fetchone():
            continue
        status, reason = row.status, row.reason
        if conn.execute(
            "SELECT 1 FROM journal_submissions WHERE response_id=?", (row.response_id,)
        ).fetchone():
            status = "edited"
            reason = "; ".join(filter(None, ["response edited after first import", row.reason]))
        conn.execute(
            """INSERT INTO journal_submissions
               (date, mood, energy, soreness, note, tags, submitted_at, source, sheet_row,
                row_hash, imported_at, status, response_id, reason)
               VALUES (?,?,?,?,?,?,?, 'form', NULL, ?,?,?,?,?)""",
            (row.date.isoformat(), row.mood, row.energy, row.soreness, row.note,
             json.dumps(row.tags), utc_stamp(row.submitted_at), digest, imported, status,
             row.response_id, reason),
        )
        counts[status] = counts.get(status, 0) + 1
    conn.commit()
    return counts
