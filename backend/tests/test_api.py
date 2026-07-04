from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_api_endpoints_return_expected_payloads() -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    overview = client.get("/api/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert "kpis" in body and "by_sector" in body and "by_zone" in body

    ask = client.post("/api/ask", json={"question": "overview"})
    assert ask.status_code == 200
    ask_body = ask.json()
    assert "answer" in ask_body and "data" in ask_body
