from __future__ import annotations

import re
from typing import Any

from backend.app.analytics.anomalies import detect_anomalies
from backend.app.analytics.forecast import forecast
from backend.app.analytics.insights import (
    consumption_by_sector,
    consumption_by_zone,
    consumption_timeseries,
    hourly_load_profile,
    overview_kpis,
    peak_hours,
    top_consumers,
)
from backend.app.analytics.recommendations import generate_recommendations
from backend.app.data.loader import get_readings
from backend.app.nlq.llm import get_llm


_INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("overview", re.compile(r"\b(total energy|how much energy|overview|summary)\b", re.I)),
    ("sector_breakdown", re.compile(r"\b(sector|by sector|which sector)\b", re.I)),
    ("zone_breakdown", re.compile(r"\b(zone|by zone|which zone|breakdown by zone)\b", re.I)),
    ("peak", re.compile(r"\b(peak|busiest hour|busiest time|peak demand|peak hours)\b", re.I)),
    ("anomalies", re.compile(r"\b(anomal|unusual|spike|problem|issue|outlier)\w*\b", re.I)),
    ("forecast", re.compile(r"\b(forecast|predict|next week|tomorrow|future)\b", re.I)),
    ("recommendations", re.compile(r"\b(save energy|reduce cost|reduce energy cost|cut cost|recommend|recommendation|how to reduce|save cost)\b", re.I)),
    ("top_consumers", re.compile(r"\b(biggest consumers|top meters|top consumers|highest consumption)\b", re.I)),
    ("renewable", re.compile(r"\b(renewable|solar|green)\b", re.I)),
]


def _detect_intent(question: str) -> str:
    lowered = question.strip().lower()
    for intent, pattern in _INTENT_PATTERNS:
        if pattern.search(lowered):
            return intent
    return "fallback"


def _compose_answer(prefix: str, body: str) -> str:
    return f"{prefix} {body}".strip()


def answer_question(question: str) -> dict[str, Any]:
    df = get_readings()
    intent = _detect_intent(question)
    llm = get_llm()

    if intent == "overview":
        kpis = overview_kpis(df)
        data = {
            "kpis": kpis,
            "by_sector": consumption_by_sector(df),
            "by_zone": consumption_by_zone(df),
        }
        answer = _compose_answer(
            "Overview:",
            f"{kpis['total_kwh']:.1f} kWh across {kpis['meter_count']} meters, "
            f"${kpis['total_cost_usd']:.2f} cost, and {kpis['renewable_share_pct']:.1f}% renewable share.",
        )
        chart = {"type": "bar", "series": data["by_sector"]}
    elif intent == "sector_breakdown":
        breakdown = consumption_by_sector(df)
        top = breakdown[0] if breakdown else None
        data = {"by_sector": breakdown, "kpis": overview_kpis(df)}
        answer = (
            f"The {top['name']} sector leads with {top['kwh']:.1f} kWh."
            if top
            else "No sector data available."
        )
        chart = {"type": "bar", "series": breakdown}
    elif intent == "zone_breakdown":
        breakdown = consumption_by_zone(df)
        top = breakdown[0] if breakdown else None
        data = {"by_zone": breakdown, "kpis": overview_kpis(df)}
        answer = (
            f"The {top['name']} zone leads with {top['kwh']:.1f} kWh."
            if top
            else "No zone data available."
        )
        chart = {"type": "bar", "series": breakdown}
    elif intent == "peak":
        peaks = peak_hours(df)
        peak_hour = peaks[0] if peaks else {"hour": None, "avg_kwh": 0.0}
        kpis = overview_kpis(df)
        data = {"peak_hours": peaks, "kpis": kpis}
        answer = f"Peak demand occurs around hour {peak_hour['hour']} with an average {peak_hour['avg_kwh']:.1f} kWh."
        chart = {"type": "line", "series": peaks}
    elif intent == "anomalies":
        anomalies = detect_anomalies(df)
        data = {"anomalies": anomalies[:25], "count": len(anomalies)}
        answer = f"Detected {len(anomalies)} anomalies, with the most severe at {anomalies[0]['timestamp'] if anomalies else 'no timestamp'}."
        chart = None
    elif intent == "forecast":
        result = forecast(df, horizon_hours=168)
        data = result
        metrics = result["metrics"]
        answer = f"Forecast generated with MAE {metrics['mae']:.2f} and MAPE {metrics['mape']:.1f}%."
        chart = {"type": "line", "series": result["forecast"]}
    elif intent == "recommendations":
        recommendations = generate_recommendations(df)
        data = {"recommendations": recommendations}
        answer = "Top recommendations: " + "; ".join(item["title"] for item in recommendations[:3])
        chart = None
    elif intent == "top_consumers":
        consumers = top_consumers(df, n=10)
        data = {"top_consumers": consumers}
        answer = f"Top consumer is {consumers[0]['meter_id'] if consumers else 'n/a'}."
        chart = {"type": "bar", "series": consumers}
    elif intent == "renewable":
        kpis = overview_kpis(df)
        by_zone = consumption_by_zone(df)
        data = {"kpis": kpis, "by_zone": by_zone}
        answer = f"Renewable share is {kpis['renewable_share_pct']:.1f}% overall."
        chart = {"type": "bar", "series": by_zone}
    else:
        data = {
            "examples": [
                "What is the overall energy summary?",
                "Which sector uses the most energy?",
                "Show anomalies and forecast next week.",
                "How can I reduce energy cost?",
            ]
        }
        answer = "I can answer questions about totals, sectors, zones, peaks, anomalies, forecasts, recommendations, top consumers, and renewable share."
        chart = None

    if llm.available and llm.name != "offline":
        llm_text = llm.complete(
            "You are a concise utility analyst.",
            f"Question: {question}\nIntent: {intent}\nAnswer: {answer}",
        )
        if llm_text.strip():
            answer = llm_text.strip()

    return {"answer": answer, "intent": intent, "data": data, "chart": chart}
