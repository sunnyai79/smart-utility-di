from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error


@dataclass(frozen=True)
class ForecastResult:
    history: list[dict[str, Any]]
    forecast: list[dict[str, Any]]
    metrics: dict[str, float]


def _aggregate_series(df: pd.DataFrame, meter_id: str | None = None, sector: str | None = None) -> pd.Series:
    frame = df.copy()
    if meter_id:
        frame = frame[frame["meter_id"] == meter_id]
    elif sector:
        frame = frame[frame["sector"].str.lower() == sector.lower()]
    series = frame.set_index("timestamp")["energy_kwh"].resample("h").sum().asfreq("h", fill_value=0.0)
    return series


def _make_features(index: pd.DatetimeIndex, values: np.ndarray) -> pd.DataFrame:
    frame = pd.DataFrame({"timestamp": index, "y": values})
    frame["trend"] = np.arange(len(frame), dtype=float)
    frame["hour"] = frame["timestamp"].dt.hour
    frame["dow"] = frame["timestamp"].dt.dayofweek
    frame["month"] = frame["timestamp"].dt.month
    frame["hour_sin"] = np.sin(2 * np.pi * frame["hour"] / 24.0)
    frame["hour_cos"] = np.cos(2 * np.pi * frame["hour"] / 24.0)
    frame["dow_sin"] = np.sin(2 * np.pi * frame["dow"] / 7.0)
    frame["dow_cos"] = np.cos(2 * np.pi * frame["dow"] / 7.0)
    frame["month_sin"] = np.sin(2 * np.pi * frame["month"] / 12.0)
    frame["month_cos"] = np.cos(2 * np.pi * frame["month"] / 12.0)
    frame["lag_24"] = frame["y"].shift(24)
    frame["lag_168"] = frame["y"].shift(168)
    frame["roll_24"] = frame["y"].shift(1).rolling(24, min_periods=6).mean()
    frame["roll_168"] = frame["y"].shift(1).rolling(168, min_periods=24).mean()
    return frame


def _feature_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[
        [
            "trend",
            "hour_sin",
            "hour_cos",
            "dow_sin",
            "dow_cos",
            "month_sin",
            "month_cos",
            "lag_24",
            "lag_168",
            "roll_24",
            "roll_168",
        ]
    ].copy()


def _fit_model(frame: pd.DataFrame) -> tuple[GradientBoostingRegressor, float, float, float]:
    usable = frame.dropna().copy()
    if len(usable) < 48:
        raise ValueError("Not enough history to fit forecast model.")
    holdout = max(24, min(168, len(usable) // 5))
    train = usable.iloc[:-holdout]
    test = usable.iloc[-holdout:]
    model = GradientBoostingRegressor(random_state=42, n_estimators=220, learning_rate=0.05, max_depth=3)
    model.fit(_feature_matrix(train), train["y"])
    predicted = model.predict(_feature_matrix(test))
    residuals = test["y"].to_numpy(dtype=float) - predicted
    mae = float(mean_absolute_error(test["y"], predicted))
    mape = float(np.mean(np.abs(residuals) / np.maximum(np.abs(test["y"].to_numpy(dtype=float)), 1.0)) * 100.0)
    return model, max(mae, 1e-6), mape, residuals.std(ddof=1) if len(residuals) > 1 else float(np.std(residuals))


def _recursive_forecast(series: pd.Series, model: GradientBoostingRegressor, horizon_hours: int) -> pd.DataFrame:
    history = list(series.to_numpy(dtype=float))
    timestamps = list(series.index)
    if not timestamps:
        return pd.DataFrame(columns=["timestamp", "kwh_pred", "lower", "upper"])
    future_rows: list[dict[str, Any]] = []
    for step in range(1, horizon_hours + 1):
        timestamp = timestamps[-1] + pd.Timedelta(hours=1)
        temp_df = _make_features(pd.DatetimeIndex([timestamp]), np.array([history[-1]], dtype=float))
        temp_df["trend"] = len(history)
        temp_df["lag_24"] = history[-24] if len(history) >= 24 else history[-1]
        temp_df["lag_168"] = history[-168] if len(history) >= 168 else history[-1]
        temp_df["roll_24"] = float(np.mean(history[-24:])) if len(history) >= 6 else float(np.mean(history))
        temp_df["roll_168"] = float(np.mean(history[-168:])) if len(history) >= 24 else float(np.mean(history))
        prediction = float(model.predict(_feature_matrix(temp_df))[0])
        prediction = max(prediction, 0.0)
        future_rows.append({"timestamp": timestamp.isoformat(), "kwh_pred": prediction})
        history.append(prediction)
        timestamps.append(timestamp)
    return pd.DataFrame(future_rows)


def _seasonal_naive(series: pd.Series, horizon_hours: int) -> ForecastResult:
    if series.empty:
        return ForecastResult(history=[], forecast=[], metrics={"mae": 0.0, "mape": 0.0})
    history_tail = series.tail(min(72, len(series)))
    forecast_rows = []
    seasonal = series.tail(min(168, len(series)))
    for step in range(1, horizon_hours + 1):
        timestamp = series.index[-1] + pd.Timedelta(hours=step)
        lookup = timestamp.hour
        candidates = seasonal[seasonal.index.hour == lookup]
        prediction = float(candidates.mean()) if not candidates.empty else float(seasonal.mean())
        forecast_rows.append({"timestamp": timestamp.isoformat(), "kwh_pred": max(prediction, 0.0), "lower": max(prediction * 0.9, 0.0), "upper": prediction * 1.1})
    metrics = {"mae": 0.0, "mape": 0.0}
    return ForecastResult(
        history=[{"timestamp": ts.isoformat(), "kwh": float(val)} for ts, val in history_tail.items()],
        forecast=forecast_rows,
        metrics=metrics,
    )


def forecast(
    df: pd.DataFrame,
    meter_id: str | None = None,
    sector: str | None = None,
    horizon_hours: int = 168,
) -> dict[str, Any]:
    series = _aggregate_series(df, meter_id=meter_id, sector=sector)
    if len(series) < 48:
        result = _seasonal_naive(series, horizon_hours)
        return {"history": result.history, "forecast": result.forecast, "metrics": result.metrics}

    frame = _make_features(series.index, series.to_numpy(dtype=float))
    try:
        model, mae, mape, residual_std = _fit_model(frame)
    except ValueError:
        result = _seasonal_naive(series, horizon_hours)
        return {"history": result.history, "forecast": result.forecast, "metrics": result.metrics}

    future = _recursive_forecast(series, model, horizon_hours)
    if future.empty:
        return {"history": [], "forecast": [], "metrics": {"mae": 0.0, "mape": 0.0}}

    scale = 1.96 * max(residual_std, mae * 0.75, 0.15)
    future["lower"] = np.clip(future["kwh_pred"] - scale, 0.0, None)
    future["upper"] = future["kwh_pred"] + scale
    history_tail = series.tail(min(72, len(series)))
    return {
        "history": [{"timestamp": ts.isoformat(), "kwh": float(val)} for ts, val in history_tail.items()],
        "forecast": future.to_dict(orient="records"),
        "metrics": {"mae": float(mae), "mape": float(mape)},
    }
