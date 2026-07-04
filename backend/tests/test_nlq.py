from __future__ import annotations

from backend.app.nlq.engine import answer_question


QUESTIONS = [
    "Give me an overview of total energy usage.",
    "Which sector uses the most energy?",
    "Which zone has the highest breakdown?",
    "What is the peak demand hour?",
    "Show anomalies and unusual spikes.",
    "Forecast next week demand.",
    "How can I reduce energy cost?",
    "What are the top meters?",
    "What is the renewable share?",
]


def test_each_intent_returns_answer() -> None:
    for question in QUESTIONS:
        result = answer_question(question)
        assert result["answer"]
        assert result["intent"]
        assert "data" in result
