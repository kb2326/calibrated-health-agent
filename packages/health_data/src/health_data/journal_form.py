"""The daily journal Google Form: its definition, and `create_form()` to (re)create it.

Uses the project's own OAuth client with Forms scopes only; the token is saved to
`Settings.forms_token_path` (gitignored). Question titles are load-bearing: the
importer maps answers to fields by title.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from health_core.settings import get_settings

FORMS_SCOPES = [
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.responses.readonly",
]
TAG_OPTIONS = ["alcohol", "caffeine after 2pm", "late meal", "high stress", "hard training"]
FORM_DESCRIPTION = (
    "30 seconds, in the evening. Rate how today actually felt - before looking at any forecast."
)


def _scale(title: str, low: str, high: str) -> dict[str, Any]:
    return {"title": title, "questionItem": {"question": {"required": True, "scaleQuestion": {
        "low": 1, "high": 10, "lowLabel": low, "highLabel": high}}}}


def form_items() -> list[dict[str, Any]]:
    """Questions in order: Date, Mood, Energy, Soreness, Note, Tags."""
    return [
        {"title": "Date", "description": "The day you're rating (usually today).",
         "questionItem": {"question": {"required": True, "dateQuestion": {
             "includeYear": True, "includeTime": False}}}},
        _scale("Mood", "Very low", "Excellent"),
        _scale("Energy", "Exhausted", "Full of energy"),
        _scale("Soreness", "None", "Very sore"),
        {"title": "Note", "description": "Optional - anything notable about today.",
         "questionItem": {"question": {"required": False, "textQuestion": {"paragraph": True}}}},
        {"title": "Tags", "description": "Optional - tick any that apply today.",
         "questionItem": {"question": {"required": False, "choiceQuestion": {
             "type": "CHECKBOX", "options": [{"value": t} for t in TAG_OPTIONS]}}}},
    ]


def create_form() -> dict[str, str]:
    """Create the Form in the owner's account; returns form_id and links."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    settings = get_settings()
    token = Path(settings.forms_token_path)
    client = Path(settings.config_dir) / "client_secret.json"
    creds = Credentials.from_authorized_user_file(str(token), FORMS_SCOPES) if token.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds = InstalledAppFlow.from_client_secrets_file(str(client), FORMS_SCOPES)\
                .run_local_server(port=0, prompt="consent", access_type="offline")
        token.parent.mkdir(parents=True, exist_ok=True)
        token.write_text(creds.to_json())

    forms = build("forms", "v1", credentials=creds)
    form = forms.forms().create(body={"info": {
        "title": "Daily check-in",
        "documentTitle": "Calibrated Health Agent - daily journal",
    }}).execute()
    form_id = form["formId"]
    requests: list[dict[str, Any]] = [{"updateFormInfo": {
        "info": {"description": FORM_DESCRIPTION}, "updateMask": "description"}}]
    requests += [{"createItem": {"item": item, "location": {"index": i}}}
                 for i, item in enumerate(form_items())]
    forms.forms().batchUpdate(formId=form_id, body={"requests": requests}).execute()
    try:  # forms created via API may start unpublished
        forms.forms().setPublishSettings(formId=form_id, body={"publishSettings": {
            "publishState": {"isPublished": True, "isAcceptingResponses": True}}}).execute()
    except Exception:  # older API surface: already published by default
        pass
    form = forms.forms().get(formId=form_id).execute()
    (Path(settings.config_dir) / "journal_form.json").write_text(
        json.dumps({"form_id": form_id}, indent=1))
    return {
        "form_id": form_id,
        "phone_link": form.get("responderUri", ""),
        "edit_link": f"https://docs.google.com/forms/d/{form_id}/edit",
    }
