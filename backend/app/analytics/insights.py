from __future__ import annotations

from typing import Any

import pandas as pd


def _apply_filters(
    df: pd.DataFrame,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    sector: str | None = None,
    zone: str | None = None,
) -> pd.DataFrame:
    frame = df.copy()
    if start is not None:
        frame = frame[frame["timestamp"] >= pd.to_datetime(start)]
    if end is not None:
        frame = frame[frame["timestamp"] <= pd.to_datetime(end)]
    if sector:
        frame = frame[frame["sector"].str.lower() == sector.lower()]
    if zone:
        frame = frame[frame["zone"].str.lower() == zone.lower()]
    return frame


def _sum_metrics(frame: pd.DataFrame) -> dict[str, float]:
    return {
        "kwh": float(frame["energy_kwh"].sum()),
        "cost": float(frame["cost_usd"].sum()),
        "co2": float(frame["co2_kg"].sum()),
    }


def overview_kpis(
    df: pd.DataFrame,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    sector: str | None = None,
    zone: str | None = None,
) -> dict[str, Any]:
    frame = _apply_filters(df, start=start, end=end, sector=sector, zone=zone)
    if frame.empty:
        return {
            "total_kwh": 0.0,
            "total_cost_usd": 0.0,
            "total_co2_kg": 0.0,
            "peak_demand_kw": 0.0,
            "peak_demand_timestamp": None,
            "renewable_share_pct": 0.0,
            "avg_daily_kwh": 0.0,
            "meter_count": 0,
        }

    hourly = frame.groupby("timestamp", as_index=False).agg(
        energy_kwh=("energy_kwh", "sum"),
        cost_usd=("cost_usd", "sum"),
        co2_kg=("co2_kg", "sum"),
        renewable_kwh=("is_renewable_kwh", "sum"),
    )
    peak_row = hourly.loc[hourly["energy_kwh"].idxmax()]
    total_kwh = float(frame["energy_kwh"].sum())
    return {
        "total_kwh": total_kwh,
        "total_cost_usd": float(frame["cost_usd"].sum()),
        "total_co2_kg": float(frame["co2_kg"].sum()),
        "peak_demand_kw": float(peak_row["energy_kwh"]),
        "peak_demand_timestamp": pd.Timestamp(peak_row["timestamp"]).isoformat(),
        "renewable_share_pct": float(frame["is_renewable_kwh"].sum() / total_kwh * 100.0) if total_kwh else 0.0,
        "avg_daily_kwh": float(total_kwh / max(frame["timestamp"].dt.normalize().nunique(), 1)),
        "meter_count": int(frame["meter_id"].nunique()),
    }


def _aggregate_breakdown(frame: pd.DataFrame, group_col: str) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    total_kwh = float(frame["energy_kwh"].sum()) or 1.0
    grouped = (
        frame.groupby(group_col, as_index=False)
        .agg(kwh=("energy_kwh", "sum"), cost=("cost_usd", "sum"), co2=("co2_kg", "sum"))
        .sort_values("kwh", ascending=False)
    )
    result: list[dict[str, Any]] = []
    for _, row in grouped.iterrows():
        result.append(
            {
                "name": str(row[group_col]),
                "kwh": float(row["kwh"]),
                "cost": float(row["cost"]),
                "co2": float(row["co2"]),
                "pct": float(row["kwh"] / total_kwh * 100.0),
            }
        )
    return result


def consumption_by_sector(
    df: pd.DataFrame,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    zone: str | None = None,
) -> list[dict[str, Any]]:
    return _aggregate_breakdown(_apply_filters(df, start=start, end=end, zone=zone), "sector")


def consumption_by_zone(
    df: pd.DataFrame,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    sector: str | None = None,
) -> list[dict[str, Any]]:
    return _aggregate_breakdown(_apply_filters(df, start=start, end=end, sector=sector), "zone")


def consumption_timeseries(
    df: pd.DataFrame,
    freq: str = "D",
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    sector: str | None = None,
    zone: str | None = None,
) -> list[dict[str, Any]]:
    frame = _apply_filters(df, start=start, end=end, sector=sector, zone=zone)
    if frame.empty:
        return []
    ts = (
        frame.set_index("timestamp")
        .resample(freq)
        .agg(energy_kwh=("energy_kwh", "sum"), cost_usd=("cost_usd", "sum"), renewable_kwh=("is_renewable_kwh", "sum"))
        .reset_index()
    )
    return [
        {
            "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
            "kwh": float(row["energy_kwh"]),
            "cost": float(row["cost_usd"]),
            "renewable_kwh": float(row["renewable_kwh"]),
        }
        for _, row in ts.iterrows()
    ]


def hourly_load_profile(
    df: pd.DataFrame,
    sector: str | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    zone: str | None = None,
) -> list[dict[str, Any]]:
    frame = _apply_filters(df, start=start, end=end, sector=sector, zone=zone)
    if frame.empty:
        return [{"hour": hour, "avg_kwh": 0.0} for hour in range(24)]
    profile = frame.groupby(frame["timestamp"].dt.hour)["energy_kwh"].mean().reindex(range(24), fill_value=0.0)
    return [{"hour": int(hour), "avg_kwh": float(value)} for hour, value in profile.items()]


def top_consumers(
    df: pd.DataFrame,
    n: int = 10,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    sector: str | None = None,
    zone: str | None = None,
) -> list[dict[str, Any]]:
    frame = _apply_filters(df, start=start, end=end, sector=sector, zone=zone)
    if frame.empty:
        return []
    grouped = (
        frame.groupby(["meter_id", "sector", "zone"], as_index=False)
        .agg(kwh=("energy_kwh", "sum"), cost=("cost_usd", "sum"), co2=("co2_kg", "sum"))
        .sort_values("kwh", ascending=False)
        .head(n)
    )
    return [
        {
            "meter_id": str(row["meter_id"]),
            "sector": str(row["sector"]),
            "zone": str(row["zone"]),
            "kwh": float(row["kwh"]),
            "cost": float(row["cost"]),
            "co2": float(row["co2"]),
        }
        for _, row in grouped.iterrows()
    ]


def peak_hours(
    df: pd.DataFrame,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    sector: str | None = None,
    zone: str | None = None,
) -> list[dict[str, Any]]:
    frame = _apply_filters(df, start=start, end=end, sector=sector, zone=zone)
    if frame.empty:
        return [{"hour": hour, "avg_kwh": 0.0} for hour in range(24)]
    hourly = frame.groupby(frame["timestamp"].dt.hour)["energy_kwh"].mean().sort_values(ascending=False)
    return [{"hour": int(hour), "avg_kwh": float(value)} for hour, value in hourly.items()]
