from __future__ import annotations

from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.app.analytics.anomalies import detect_anomalies
from backend.app.analytics.forecast import forecast
from backend.app.analytics.insights import (
    consumption_by_sector,
    consumption_by_zone,
    consumption_timeseries,
    hourly_load_profile,
    overview_kpis,
    top_consumers,
)
from backend.app.analytics.recommendations import generate_recommendations
from backend.app.config import PROJECT_ROOT, get_settings
from backend.app.data.loader import get_readings
from backend.app.nlq.engine import answer_question
from backend.app.nlq.llm import get_llm

app = FastAPI(title="Smart Utility DI Platform", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str


frontend_dir = PROJECT_ROOT / "frontend"


@app.get("/api/health")
def health() -> dict[str, Any]:
    df = get_readings()
    return {"status": "ok", "rows": int(len(df)), "meters": int(df["meter_id"].nunique())}


@app.get("/api/overview")
def api_overview() -> dict[str, Any]:
    df = get_readings()
    return {
        "kpis": overview_kpis(df),
        "by_sector": consumption_by_sector(df),
        "by_zone": consumption_by_zone(df),
    }


@app.get("/api/timeseries")
def api_timeseries(freq: str = Query("D"), sector: str | None = None, zone: str | None = None) -> dict[str, Any]:
    return {"items": consumption_timeseries(get_readings(), freq=freq, sector=sector, zone=zone)}


@app.get("/api/load-profile")
def api_load_profile(sector: str | None = None) -> dict[str, Any]:
    return {"items": hourly_load_profile(get_readings(), sector=sector)}


@app.get("/api/anomalies")
def api_anomalies(limit: int = Query(25, ge=1, le=500)) -> dict[str, Any]:
    anomalies = detect_anomalies(get_readings())
    return {"count": len(anomalies), "items": anomalies[:limit]}


@app.get("/api/forecast")
def api_forecast(
    sector: str | None = None,
    meter_id: str | None = None,
    horizon: int = Query(168, ge=24, le=24 * 30),
) -> dict[str, Any]:
    return forecast(get_readings(), sector=sector, meter_id=meter_id, horizon_hours=horizon)


@app.get("/api/recommendations")
def api_recommendations() -> dict[str, Any]:
    return {"items": generate_recommendations(get_readings())}


@app.get("/api/top-consumers")
def api_top_consumers(n: int = Query(10, ge=1, le=100)) -> dict[str, Any]:
    return {"items": top_consumers(get_readings(), n=n)}


@app.post("/api/ask")
def api_ask(payload: AskRequest) -> dict[str, Any]:
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty.")
    return answer_question(payload.question)


@app.get("/api/meta")
def api_meta() -> dict[str, Any]:
    df = get_readings()
    settings = get_settings()
    llm = get_llm()
    return {
        "sectors": sorted(df["sector"].unique().tolist()),
        "zones": sorted(df["zone"].unique().tolist()),
        "date_range": {
            "start": df["timestamp"].min().isoformat(),
            "end": df["timestamp"].max().isoformat(),
        },
        "llm_provider": llm.name,
        "data_dir": str(settings.data_dir),
    }


if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
else:
    @app.get("/")
    def _root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/docs")


if __name__ == "__main__":
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=False)
