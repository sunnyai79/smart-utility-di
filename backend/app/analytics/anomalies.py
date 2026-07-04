from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def detect_anomalies(
    df: pd.DataFrame,
    method: str = "zscore",
    window: int = 24 * 7,
    z: float = 3.0,
) -> list[dict[str, Any]]:
    if df.empty:
        return []
    if method != "zscore":
        raise ValueError("Only method='zscore' is supported.")

    frame = df.sort_values(["meter_id", "timestamp"]).copy()
    frame["hour"] = frame["timestamp"].dt.hour
    frame["expected_rolling"] = (
        frame.groupby("meter_id")["energy_kwh"]
        .transform(lambda s: s.shift(1).rolling(window=window, min_periods=24).mean())
    )
    frame["expected_hourly"] = (
        frame.groupby(["meter_id", "hour"])["energy_kwh"]
        .transform(lambda s: s.shift(1).expanding(min_periods=6).mean())
    )
    frame["expected_kwh"] = frame["expected_rolling"].combine_first(frame["expected_hourly"])
    frame["expected_kwh"] = frame["expected_kwh"].fillna(frame.groupby("meter_id")["energy_kwh"].transform("median"))
    frame["residual"] = frame["energy_kwh"] - frame["expected_kwh"]
    frame["rolling_std"] = (
        frame.groupby("meter_id")["energy_kwh"]
        .transform(lambda s: s.shift(1).rolling(window=window, min_periods=24).std())
        .fillna(frame.groupby("meter_id")["energy_kwh"].transform("std"))
        .fillna(frame["energy_kwh"].std())
    )
    frame["seasonal_std"] = (
        frame.groupby(["meter_id", "hour"])["energy_kwh"]
        .transform(lambda s: s.shift(1).expanding(min_periods=6).std())
        .fillna(frame.groupby("meter_id")["energy_kwh"].transform("std"))
    )
    frame["effective_std"] = np.minimum(frame["rolling_std"], frame["seasonal_std"])
    frame["effective_std"] = frame["effective_std"].replace(0.0, np.nan).fillna(0.08)
    frame["zscore"] = frame["residual"].abs() / frame["effective_std"]
    detected = frame[(frame["zscore"] >= z) | (frame["residual"].abs() >= frame["expected_kwh"].abs() * 0.65)].copy()
    if detected.empty:
        return []
    detected["severity"] = detected["zscore"] + detected["residual"].abs() / (detected["expected_kwh"].abs() + 0.1)
    detected = detected.sort_values(["severity", "timestamp"], ascending=[False, True])
    return [
        {
            "meter_id": str(row["meter_id"]),
            "sector": str(row["sector"]),
            "zone": str(row["zone"]),
            "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
            "energy_kwh": float(row["energy_kwh"]),
            "expected_kwh": float(row["expected_kwh"]),
            "deviation": float(row["residual"]),
            "severity": float(row["severity"]),
        }
        for _, row in detected.iterrows()
    ]
