from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False, extra="ignore")

    gemini_api_key: str | None = Field(default=None)
    data_dir: Path = Field(default_factory=lambda: PROJECT_ROOT / "data")
    days: int = Field(default=120)
    seed: int = Field(default=42)

    @field_validator("data_dir", mode="before")
    @classmethod
    def _resolve_data_dir(cls, value: object) -> Path:
        if value in {None, ""}:
            return PROJECT_ROOT / "data"
        path = Path(str(value))
        return path if path.is_absolute() else PROJECT_ROOT / path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
