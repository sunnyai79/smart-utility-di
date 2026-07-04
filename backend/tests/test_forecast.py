from __future__ import annotations

import math

from backend.app.analytics.forecast import forecast
from backend.app.data.generate import generate_readings


def test_forecast_returns_horizon_and_metrics() -> None:
    df = generate_readings(days=30, seed=5)
    result = forecast(df, horizon_hours=48)
    assert len(result["forecast"]) == 48
    assert result["metrics"]["mae"] >= 0
    assert result["metrics"]["mape"] >= 0
    assert result["history"]
    for row in result["forecast"]:
        assert math.isfinite(row["kwh_pred"])
        assert math.isfinite(row["lower"])
        assert math.isfinite(row["upper"])
        assert row["lower"] <= row["kwh_pred"] <= row["upper"]
