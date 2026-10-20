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


def test_defaults_pin_project_and_timezone():
    s = Settings()
    assert s.gcp_project == "artful-timing-506108-n8" and s.timezone == "Asia/Kolkata"
