from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import requests

from backend.app.config import get_settings


class LLMProvider(Protocol):
    available: bool
    name: str

    def complete(self, system: str, prompt: str) -> str: ...


@dataclass
class OfflineProvider:
    available: bool = True
    name: str = "offline"

    def complete(self, system: str, prompt: str) -> str:
        summary = prompt.splitlines()
        bullets = [line[2:].strip() for line in summary if line.startswith("- ")]
        if bullets:
            return "Offline summary: " + "; ".join(bullets[:3])
        return "Offline summary: deterministic insight generation is active."


@dataclass
class GeminiProvider:
    api_key: str
    model: str = "gemini-1.5-flash"
    available: bool = True
    name: str = "gemini"

    def complete(self, system: str, prompt: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 256},
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
                text = "".join(texts).strip()
                if text:
                    return text
        except Exception:
            pass
        return OfflineProvider().complete(system, prompt)


def get_llm() -> LLMProvider:
    settings = get_settings()
    if settings.gemini_api_key:
        return GeminiProvider(api_key=settings.gemini_api_key)
    return OfflineProvider()
