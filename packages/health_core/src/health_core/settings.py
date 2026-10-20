"""Runtime settings for every package, read from CHA_-prefixed environment variables."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHA_", env_file=".env", extra="ignore")

    data_mode: Literal["real", "synthetic"] = "real"
    data_dir: Path = Path("data")
    config_dir: Path = Path("config")
    gcp_project: str = "artful-timing-506108-n8"
    gcp_region: str = "us-central1"
    db_bucket: str | None = None
    db_object: str = "health.db"
    token_secret: str | None = None
    client_secret_secret: str | None = None
    journal_sheet_id: str | None = None
    timezone: str = "Asia/Kolkata"
    # Verified against https://ai.google.dev/gemini-api/docs/models (stable).
    model_default: str = "gemini-3.5-flash-lite"

    @property
    def db_path(self) -> Path:
        name = "synthetic.db" if self.data_mode == "synthetic" else "health.db"
        return self.data_dir / name


@lru_cache
def get_settings() -> Settings:
    return Settings()
