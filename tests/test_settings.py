import os

import pytest
from health_core.settings import Settings
from pydantic import ValidationError


def test_db_path_real(monkeypatch, tmp_path):
    monkeypatch.setenv("CHA_DATA_DIR", str(tmp_path))
    assert Settings().db_path == tmp_path / "health.db"


def test_db_path_synthetic(monkeypatch, tmp_path):
    monkeypatch.setenv("CHA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CHA_DATA_MODE", "synthetic")
    assert Settings().db_path == tmp_path / "synthetic.db"


def test_rejects_unknown_mode(monkeypatch):
    monkeypatch.setenv("CHA_DATA_MODE", "prod")
    with pytest.raises(ValidationError):
        Settings()


def test_defaults_pin_project_and_timezone(monkeypatch):
    for key in [k for k in os.environ if k.startswith("CHA_")]:
        monkeypatch.delenv(key)
    s = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert s.gcp_project == "artful-timing-506108-n8" and s.timezone == "Asia/Kolkata"


def test_forms_settings_defaults(monkeypatch):
    for key in [k for k in os.environ if k.startswith("CHA_")]:
        monkeypatch.delenv(key)
    s = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert s.journal_form_id is None
    assert str(s.forms_token_path).replace("\\", "/") == "config/forms_token.json"
    assert s.forms_token_secret is None
