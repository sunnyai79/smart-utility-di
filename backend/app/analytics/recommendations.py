from __future__ import annotations

from typing import Any

import pandas as pd

from backend.app.analytics.anomalies import detect_anomalies
from backend.app.analytics.insights import peak_hours
from backend.app.nlq.llm import get_llm


def _peak_offpeak_delta(df: pd.DataFrame) -> tuple[float, float, float]:
    frame = df.copy()
    frame["hour"] = frame["timestamp"].dt.hour
    peak = frame[(frame["hour"] >= 17) & (frame["hour"] <= 21)]
    off_peak = frame[(frame["hour"] < 7) | (frame["hour"] > 21)]
    if peak.empty or off_peak.empty:
        return 0.0, 0.0, 0.0
    peak_rate = float((peak["cost_usd"].sum() / peak["energy_kwh"].sum()) if peak["energy_kwh"].sum() else 0.0)
    off_rate = float((off_peak["cost_usd"].sum() / off_peak["energy_kwh"].sum()) if off_peak["energy_kwh"].sum() else 0.0)
    delta = max(peak_rate - off_rate, 0.0)
    potential_shift_kwh = float(min(peak["energy_kwh"].sum() * 0.08, peak["energy_kwh"].sum()))
    return peak_rate, off_rate, potential_shift_kwh * delta


def _base_load_meter_candidates(df: pd.DataFrame) -> pd.DataFrame:
    hourly = df.groupby(["meter_id", "sector", "zone"], as_index=False).agg(
        kwh=("energy_kwh", "sum"),
        avg_hourly=("energy_kwh", "mean"),
    )
    hourly["base_load_ratio"] = hourly["avg_hourly"] / hourly["kwh"].replace(0.0, pd.NA)
    return hourly.sort_values("kwh", ascending=False)


def generate_recommendations(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []

    recommendations: list[dict[str, Any]] = []

    peak_rate, off_rate, est_shift_savings = _peak_offpeak_delta(df)
    if est_shift_savings > 0:
        recommendations.append(
            {
                "title": "Shift flexible loads away from peak tariff hours",
                "category": "demand-shaping",
                "impact": "High",
                "detail": f"Peak energy averages ${peak_rate:.3f}/kWh vs ${off_rate:.3f}/kWh off-peak. Moving about 8% of peak-hour load can save roughly {est_shift_savings:.1f} USD over the selected period.",
                "est_savings_kwh": float(df[(df["timestamp"].dt.hour >= 17) & (df["timestamp"].dt.hour <= 21)]["energy_kwh"].sum() * 0.08),
                "est_savings_usd": float(est_shift_savings),
                "priority": 1,
            }
        )

    meter_summary = _base_load_meter_candidates(df)
    top_meter = meter_summary.iloc[0] if not meter_summary.empty else None
    if top_meter is not None:
        top_meter_row = df[df["meter_id"] == top_meter["meter_id"]]
        base_load_estimate = float(top_meter_row["energy_kwh"].quantile(0.1))
        excess = top_meter_row["energy_kwh"].clip(lower=base_load_estimate)
        est_kwh = float(excess.sum() * 0.06)
        est_usd = float((est_kwh * df["cost_usd"].sum() / max(df["energy_kwh"].sum(), 1.0)))
        recommendations.append(
            {
                "title": f"Inspect {top_meter['meter_id']} for high baseline consumption",
                "category": "efficiency",
                "impact": "High",
                "detail": f"{top_meter['meter_id']} in {top_meter['sector']} / {top_meter['zone']} is among the largest consumers. A small 6% efficiency gain could save about {est_kwh:.1f} kWh.",
                "est_savings_kwh": est_kwh,
                "est_savings_usd": est_usd,
                "priority": 2,
            }
        )

    renewable_by_zone = (
        df.groupby("zone", as_index=False)
        .agg(renewable_kwh=("is_renewable_kwh", "sum"), total_kwh=("energy_kwh", "sum"))
    )
    renewable_by_zone["renewable_share_pct"] = 100.0 * renewable_by_zone["renewable_kwh"] / renewable_by_zone["total_kwh"].replace(0.0, pd.NA)
    low_zone = renewable_by_zone.sort_values("renewable_share_pct").iloc[0]
    recommendations.append(
        {
            "title": f"Improve renewable penetration in {low_zone['zone']}",
            "category": "sustainability",
            "impact": "Medium",
            "detail": f"{low_zone['zone']} has the lowest renewable share at {float(low_zone['renewable_share_pct']):.1f}%. Better solar dispatch or storage could improve the mix.",
            "est_savings_kwh": 0.0,
            "est_savings_usd": 0.0,
            "priority": 3,
        }
    )

    anomaly_count = len(detect_anomalies(df))
    if anomaly_count:
        recommendations.append(
            {
                "title": "Review anomaly alerts for equipment maintenance",
                "category": "operations",
                "impact": "Medium",
                "detail": f"The anomaly detector flagged {anomaly_count} unusual meter readings. Investigating these events may prevent follow-on losses and improve reliability.",
                "est_savings_kwh": float(min(anomaly_count * 0.5, 20.0)),
                "est_savings_usd": float(min(anomaly_count * 0.5, 20.0) * df["cost_usd"].sum() / max(df["energy_kwh"].sum(), 1.0)),
                "priority": 4,
            }
        )

    low_hours = peak_hours(df)[-3:]
    if low_hours:
        recommendations.append(
            {
                "title": "Use low-demand hours for pre-cooling and batch work",
                "category": "operations",
                "impact": "Medium",
                "detail": "The quietest hours can absorb discretionary usage. Scheduling HVAC pre-cooling or batch loads there smooths the load curve and reduces peak exposure.",
                "est_savings_kwh": float(sum(item["avg_kwh"] for item in low_hours) * 0.03),
                "est_savings_usd": float(sum(item["avg_kwh"] for item in low_hours) * 0.03 * df["cost_usd"].sum() / max(df["energy_kwh"].sum(), 1.0)),
                "priority": 5,
            }
        )

    provider = get_llm()
    if provider.available:
        narrative_prompt = "\n".join(
            [
                "Summarize the following utility recommendations in 3 concise bullets.",
                *[f"- {item['title']}: {item['detail']}" for item in recommendations[:4]],
            ]
        )
        summary = provider.complete(
            "You are a concise energy-efficiency analyst.",
            narrative_prompt,
        )
    else:
        summary = "Focus on peak shifting, highest-load meters, renewable share gaps, and flagged anomalies."

    if recommendations:
        recommendations[0]["narrative"] = summary
    return sorted(recommendations, key=lambda item: item["priority"])
