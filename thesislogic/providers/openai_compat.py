"""Provider for any OpenAI-compatible chat/embeddings endpoint.

Covers local servers (llama.cpp `llama-server`, Ollama, vLLM, LM Studio, TGI)
and hosted OpenAI-compatible APIs. Point THESISLOGIC_GENERATION_BASE_URL at
the server root (e.g. http://127.0.0.1:8080); /v1 is appended automatically.
"""

from __future__ import annotations

import httpx

from .base import GenerationResult


def _v1(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/v1") else base + "/v1"


class OpenAICompatProvider:
    name = "openai_compatible"

    def __init__(self, base_url: str, model: str = "", api_key: str = "", timeout: int = 180):
        self.base_url = _v1(base_url)
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def generate(self, system: str, prompt: str, max_tokens: int = 1600) -> GenerationResult:
        payload = {
            "model": self.model or "default",
            "max_tokens": max_tokens,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            resp = httpx.post(f"{self.base_url}/chat/completions", json=payload,
                              headers=self._headers(), timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
            return GenerationResult(text=text.strip(), provider=self.name,
                                    model=data.get("model", self.model), live=bool(text.strip()),
                                    usage=data.get("usage") or {})
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return GenerationResult(text="", provider=self.name, model=self.model,
                                    live=False, error=f"{type(exc).__name__}: {exc}")

    def health(self) -> dict:
        try:
            resp = httpx.get(f"{self.base_url}/models", headers=self._headers(), timeout=10)
            ready = resp.status_code == 200
            models = []
            if ready:
                models = [m.get("id") for m in resp.json().get("data", [])]
            return {"provider": self.name, "ready": ready, "base_url": self.base_url,
                    "configured_model": self.model, "served_models": models[:10]}
        except httpx.HTTPError as exc:
            return {"provider": self.name, "ready": False, "base_url": self.base_url,
                    "detail": str(exc)}


class OpenAICompatEmbeddings:
    name = "openai_compatible"

    def __init__(self, base_url: str, model: str = "", api_key: str = "", timeout: int = 120):
        self.base_url = _v1(base_url)
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        try:
            resp = httpx.post(f"{self.base_url}/embeddings",
                              json={"model": self.model or "default", "input": texts},
                              headers=self._headers(), timeout=self.timeout)
            resp.raise_for_status()
            data = sorted(resp.json().get("data", []), key=lambda d: d.get("index", 0))
            vectors = [d.get("embedding") for d in data]
            return vectors if len(vectors) == len(texts) else None
        except (httpx.HTTPError, ValueError):
            return None

    def health(self) -> dict:
        probe = self.embed(["health check"])
        return {"provider": self.name, "ready": probe is not None, "base_url": self.base_url,
                "configured_model": self.model,
                "dimensions": len(probe[0]) if probe else None}
