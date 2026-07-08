"""Cloud provider for Google Gemini models via the Generative Language API.

No SDK dependency — the REST surface is called directly with httpx.
Configure:
    THESISLOGIC_GENERATION_PROVIDER=gemini
    THESISLOGIC_GENERATION_MODEL=gemini-2.5-pro   (default)
    THESISLOGIC_GENERATION_API_KEY=...  (or GEMINI_API_KEY / GOOGLE_API_KEY)
"""

from __future__ import annotations

import os

import httpx

from .base import GenerationResult

DEFAULT_MODEL = "gemini-2.5-pro"
API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    name = "gemini"

    def __init__(self, model: str = "", api_key: str = "", timeout: int = 180):
        self.model = model or DEFAULT_MODEL
        self.api_key = (api_key or os.environ.get("GEMINI_API_KEY", "")
                        or os.environ.get("GOOGLE_API_KEY", ""))
        self.timeout = timeout

    def generate(self, system: str, prompt: str, max_tokens: int = 1600) -> GenerationResult:
        if not self.api_key:
            return GenerationResult(
                text="", provider=self.name, model=self.model, live=False,
                error="missing API key (set THESISLOGIC_GENERATION_API_KEY or GEMINI_API_KEY)")
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.1},
        }
        try:
            resp = httpx.post(f"{API_BASE}/models/{self.model}:generateContent",
                              params={"key": self.api_key}, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates") or []
            content = (candidates[0].get("content") or {}) if candidates else {}
            text = "".join(part.get("text", "") for part in content.get("parts") or [])
            usage = data.get("usageMetadata") or {}
            return GenerationResult(
                text=text.strip(), provider=self.name, model=self.model,
                live=bool(text.strip()),
                error="" if text.strip() else "empty or safety-blocked response",
                usage={"input_tokens": usage.get("promptTokenCount"),
                       "output_tokens": usage.get("candidatesTokenCount")})
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            return GenerationResult(text="", provider=self.name, model=self.model,
                                    live=False, error=f"{type(exc).__name__}: {exc}")

    def health(self) -> dict:
        if not self.api_key:
            return {"provider": self.name, "ready": False, "configured_model": self.model,
                    "detail": "missing API key"}
        try:
            resp = httpx.get(f"{API_BASE}/models/{self.model}",
                             params={"key": self.api_key}, timeout=10)
            ready = resp.status_code == 200
            return {"provider": self.name, "ready": ready, "configured_model": self.model,
                    "detail": "" if ready else f"HTTP {resp.status_code}: {resp.text[:120]}"}
        except httpx.HTTPError as exc:
            return {"provider": self.name, "ready": False, "configured_model": self.model,
                    "detail": str(exc)}
