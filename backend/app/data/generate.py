from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

REFERENCE_NOW = pd.Timestamp("2026-07-01 23:00:00")
SECTORS = ("residential", "commercial", "industrial", "municipal")
ZONES = ("North", "South", "East", "West", "Central")
DEFAULT_ANOMALY_COUNT = 15


@dataclass(frozen=True)
class SimulationArtifacts:
    readings: pd.DataFrame
    anomaly_truth: list[dict[str, object]]


def _build_meter_catalog(seed: int, meter_count: int = 40) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    sector_cycle = np.array([*SECTORS])
    sectors = np.resize(sector_cycle, meter_count)
    zone_cycle = np.array([*ZONES, *ZONES[::-1]])
    zones = np.resize(zone_cycle, meter_count)
    base_ranges = {
        "residential": (1.8, 4.4),
        "commercial": (5.0, 14.0),
        "industrial": (8.0, 22.0),
        "municipal": (2.4, 7.5),
    }
    rows: list[dict[str, object]] = []
    for idx in range(meter_count):
        sector = str(sectors[idx])
        zone = str(zones[(idx + seed) % len(zones)])
        base_min, base_max = base_ranges[sector]
        base_load_kw = float(np.round(rng.uniform(base_min, base_max), 2))
        capacity_kw = float(np.round(base_load_kw * rng.uniform(2.1, 3.0), 2))
        rows.append(
            {
                "meter_id": f"M{idx + 1:03d}",
                "sector": sector,
                "zone": zone,
                "base_load_kw": base_load_kw,
                "capacity_kw": capacity_kw,
            }
        )
    return pd.DataFrame(rows)


def _gaussian_peak(hour: np.ndarray, center: float, width: float, amplitude: float) -> np.ndarray:
    return amplitude * np.exp(-0.5 * ((hour - center) / width) ** 2)


def _sector_profile(sector: pd.Series, hour: np.ndarray) -> np.ndarray:
    profile = np.full(hour.shape, 0.35, dtype=float)
    residential = sector == "residential"
    commercial = sector == "commercial"
    industrial = sector == "industrial"
    municipal = sector == "municipal"

    profile[residential] = (
        0.45
        + _gaussian_peak(hour[residential], 8.0, 1.6, 0.95)
        + _gaussian_peak(hour[residential], 19.0, 2.0, 1.15)
    )
    profile[commercial] = 0.42 + _gaussian_peak(hour[commercial], 13.0, 3.2, 1.35)
    profile[industrial] = 0.78 + _gaussian_peak(hour[industrial], 14.0, 5.0, 0.55)
    profile[municipal] = 0.40 + _gaussian_peak(hour[municipal], 10.0, 4.2, 0.28)
    return profile


def _temperature_from_time(timestamp: pd.Series) -> np.ndarray:
    day_of_year = timestamp.dt.dayofyear.to_numpy(dtype=float)
    hour = timestamp.dt.hour.to_numpy(dtype=float)
    seasonal = 18.0 + 10.5 * np.sin(2.0 * np.pi * (day_of_year - 172.0) / 365.0)
    diurnal = 3.0 * np.sin(2.0 * np.pi * (hour - 15.0) / 24.0)
    return seasonal + diurnal


def _renewable_share(zone: pd.Series, hour: np.ndarray, temperature_c: np.ndarray) -> np.ndarray:
    zone_base = {
        "North": 0.12,
        "South": 0.18,
        "East": 0.22,
        "West": 0.17,
        "Central": 0.14,
    }
    base = zone.map(zone_base).to_numpy(dtype=float)
    solar = np.clip(np.sin(np.pi * np.clip((hour - 6.0) / 12.0, 0.0, 1.0)), 0.0, 1.0)
    weather_boost = np.clip((temperature_c - 15.0) / 30.0, 0.0, 0.15)
    share = base + 0.28 * solar + weather_boost
    return np.clip(share, 0.05, 0.68)


def _time_of_use_rate(hour: np.ndarray) -> np.ndarray:
    rates = np.full(hour.shape, 0.18, dtype=float)
    rates[(hour >= 17) & (hour <= 21)] = 0.29
    rates[(hour >= 7) & (hour <= 16)] = 0.21
    rates[(hour < 7) | (hour > 21)] = 0.14
    return rates


def _emission_factor(zone: pd.Series) -> np.ndarray:
    factors = {
        "North": 0.41,
        "South": 0.38,
        "East": 0.35,
        "West": 0.39,
        "Central": 0.40,
    }
    return zone.map(factors).to_numpy(dtype=float)


def _build_base_frame(days: int, seed: int, reference_now: pd.Timestamp) -> pd.DataFrame:
    catalog = _build_meter_catalog(seed)
    timestamps = pd.date_range(end=reference_now, periods=days * 24, freq="h")
    time_frame = pd.DataFrame({"timestamp": timestamps})
    time_frame["hour"] = time_frame["timestamp"].dt.hour
    time_frame["dayofweek"] = time_frame["timestamp"].dt.dayofweek
    time_frame["dayofyear"] = time_frame["timestamp"].dt.dayofyear

    catalog = catalog.assign(_key=1)
    time_frame = time_frame.assign(_key=1)
    frame = catalog.merge(time_frame, on="_key", how="inner").drop(columns="_key")
    frame = frame.sort_values(["timestamp", "meter_id"], ignore_index=True)

    rng = np.random.default_rng(seed)
    hour = frame["hour"].to_numpy(dtype=float)
    dayofweek = frame["dayofweek"].to_numpy(dtype=int)
    temperature_c = _temperature_from_time(frame["timestamp"])
    profile = _sector_profile(frame["sector"], hour)
    weekend_factor = np.where(dayofweek >= 5, 0.84, 1.0)
    commercial_weekend = np.where((frame["sector"] == "commercial") & (dayofweek >= 5), 0.72, 1.0)
    industrial_weekend = np.where((frame["sector"] == "industrial") & (dayofweek >= 5), 0.88, 1.0)
    weekend_factor = weekend_factor * commercial_weekend * industrial_weekend
    temp_factor = 1.0 + np.clip(temperature_c - 22.0, 0.0, None) * 0.022
    temp_factor += np.clip(16.0 - temperature_c, 0.0, None) * 0.007
    zone_factor = frame["zone"].map(
        {
            "North": 0.97,
            "South": 1.03,
            "East": 1.01,
            "West": 0.99,
            "Central": 1.00,
        }
    ).to_numpy(dtype=float)
    meter_noise = rng.normal(0.0, 0.08, size=len(frame))
    energy_kwh = (
        frame["base_load_kw"].to_numpy(dtype=float)
        * profile
        * weekend_factor
        * temp_factor
        * zone_factor
        * (1.0 + meter_noise)
    )
    energy_kwh = np.clip(energy_kwh, 0.08, frame["capacity_kw"].to_numpy(dtype=float) * 1.2)
    renewable_share = _renewable_share(frame["zone"], hour, temperature_c)
    renewable_kwh = energy_kwh * renewable_share
    rate = _time_of_use_rate(hour)
    cost_usd = energy_kwh * rate
    co2_kg = np.clip((energy_kwh - renewable_kwh), 0.0, None) * _emission_factor(frame["zone"])
    voltage = 120.0 + np.clip((energy_kwh / frame["capacity_kw"].to_numpy(dtype=float)) - 0.45, -0.25, 0.45) * 3.8
    voltage += rng.normal(0.0, 0.45, size=len(frame))

    frame["temperature_c"] = np.round(temperature_c, 2)
    frame["energy_kwh"] = np.round(energy_kwh, 3)
    frame["is_renewable_kwh"] = np.round(renewable_kwh, 3)
    frame["cost_usd"] = np.round(cost_usd, 3)
    frame["co2_kg"] = np.round(co2_kg, 3)
    frame["voltage"] = np.round(voltage, 2)
    return frame[
        [
            "timestamp",
            "meter_id",
            "sector",
            "zone",
            "energy_kwh",
            "temperature_c",
            "cost_usd",
            "co2_kg",
            "is_renewable_kwh",
            "voltage",
        ]
    ]


def _choose_anomaly_indices(frame: pd.DataFrame, seed: int, count: int) -> np.ndarray:
    rng = np.random.default_rng(seed + 913)
    timestamps = pd.to_datetime(frame["timestamp"])
    lower = timestamps.min() + pd.Timedelta(days=14)
    upper = timestamps.max() - pd.Timedelta(days=7)
    candidates = frame.index[(timestamps >= lower) & (timestamps <= upper)].to_numpy()
    if len(candidates) < count:
        candidates = frame.index.to_numpy()
    return np.sort(rng.choice(candidates, size=count, replace=False))


def _apply_anomalies(frame: pd.DataFrame, indices: Iterable[int], seed: int) -> list[dict[str, object]]:
    rng = np.random.default_rng(seed + 2048)
    anomaly_factors = np.array([0.22, 0.28, 0.36, 2.45, 3.1, 4.0])
    anomaly_types = np.array(["drop", "drop", "drop", "spike", "spike", "spike"])
    truth: list[dict[str, object]] = []
    for idx in indices:
        factor_index = int(rng.integers(0, len(anomaly_factors)))
        factor = float(anomaly_factors[factor_index])
        anomaly_type = str(anomaly_types[factor_index])
        original = float(frame.at[idx, "energy_kwh"])
        new_energy = max(0.05, original * factor)
        ratio = new_energy / original if original else 1.0
        frame.at[idx, "energy_kwh"] = round(new_energy, 3)
        frame.at[idx, "cost_usd"] = round(float(frame.at[idx, "cost_usd"]) * ratio, 3)
        frame.at[idx, "co2_kg"] = round(float(frame.at[idx, "co2_kg"]) * ratio, 3)
        frame.at[idx, "is_renewable_kwh"] = round(float(frame.at[idx, "is_renewable_kwh"]) * ratio, 3)
        frame.at[idx, "voltage"] = round(float(frame.at[idx, "voltage"]) + (3.5 if anomaly_type == "spike" else -2.8), 2)
        truth.append(
            {
                "meter_id": str(frame.at[idx, "meter_id"]),
                "timestamp": pd.Timestamp(frame.at[idx, "timestamp"]).isoformat(),
                "anomaly_type": anomaly_type,
                "factor": factor,
            }
        )
    return truth


def build_simulation(
    days: int,
    seed: int,
    reference_now: pd.Timestamp = REFERENCE_NOW,
    anomaly_count: int = DEFAULT_ANOMALY_COUNT,
) -> SimulationArtifacts:
    frame = _build_base_frame(days=days, seed=seed, reference_now=reference_now)
    indices = _choose_anomaly_indices(frame, seed=seed, count=anomaly_count)
    truth = _apply_anomalies(frame, indices=indices, seed=seed)
    return SimulationArtifacts(readings=frame, anomaly_truth=truth)


def generate_readings(
    days: int,
    seed: int,
    reference_now: pd.Timestamp = REFERENCE_NOW,
    anomaly_count: int = DEFAULT_ANOMALY_COUNT,
) -> pd.DataFrame:
    return build_simulation(days=days, seed=seed, reference_now=reference_now, anomaly_count=anomaly_count).readings


def generate_anomaly_truth(
    days: int,
    seed: int,
    reference_now: pd.Timestamp = REFERENCE_NOW,
    anomaly_count: int = DEFAULT_ANOMALY_COUNT,
) -> list[dict[str, object]]:
    return build_simulation(days=days, seed=seed, reference_now=reference_now, anomaly_count=anomaly_count).anomaly_truth


def save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, date_format="%Y-%m-%d %H:%M:%S")


def load_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["timestamp"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=False)
    return frame


def save_truth_json(truth: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(truth, indent=2), encoding="utf-8")
