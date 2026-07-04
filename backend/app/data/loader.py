from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from backend.app.config import get_settings
from backend.app.data.generate import generate_readings, load_csv, save_csv

_READINGS_CACHE: pd.DataFrame | None = None
_READINGS_SOURCE: Path | None = None


def readings_path() -> Path:
    return get_settings().data_dir / "readings.csv"


def get_readings() -> pd.DataFrame:
    global _READINGS_CACHE, _READINGS_SOURCE
    path = readings_path()
    if _READINGS_CACHE is not None and _READINGS_SOURCE == path:
        return _READINGS_CACHE

    settings = get_settings()
    if path.exists():
        frame = load_csv(path)
    else:
        frame = generate_readings(days=settings.days, seed=settings.seed)
        save_csv(frame, path)

    _READINGS_CACHE = frame
    _READINGS_SOURCE = path
    return frame


def clear_cache() -> None:
    global _READINGS_CACHE, _READINGS_SOURCE
    _READINGS_CACHE = None
    _READINGS_SOURCE = None
