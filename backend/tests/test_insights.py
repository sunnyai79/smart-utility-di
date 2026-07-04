from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.analytics.insights import (
    consumption_by_sector,
    consumption_by_zone,
    consumption_timeseries,
    hourly_load_profile,
    overview_kpis,
    peak_hours,
    top_consumers,
)
from backend.app.config import get_settings
from backend.app.data.generate import generate_readings


def _small_frame() -> pd.DataFrame:
    return generate_readings(days=30, seed=7)


def test_overview_and_breakdowns_are_consistent() -> None:
    df = _small_frame()
    kpis = overview_kpis(df)
    sector = consumption_by_sector(df)
    zone = consumption_by_zone(df)
    assert kpis["total_kwh"] > 0
    assert kpis["total_cost_usd"] > 0
    assert kpis["meter_count"] == 40
    assert abs(sum(item["kwh"] for item in sector) - kpis["total_kwh"]) < 1e-6
    assert abs(sum(item["kwh"] for item in zone) - kpis["total_kwh"]) < 1e-6
    assert 0 <= kpis["renewable_share_pct"] <= 100


def test_timeseries_and_profiles() -> None:
    df = _small_frame()
    series = consumption_timeseries(df, freq="D")
    load = hourly_load_profile(df)
    peaks = peak_hours(df)
    top = top_consumers(df, n=5)
    assert series
    assert len(load) == 24
    assert len(peaks) == 24
    assert len(top) == 5
    assert all("timestamp" in row for row in series)
