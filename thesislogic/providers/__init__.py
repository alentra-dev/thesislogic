"""AI provider abstraction.

A firm chooses its posture with two environment variables:

    THESISLOGIC_GENERATION_PROVIDER = none | openai_compatible | anthropic | openai | gemini
    THESISLOGIC_EMBEDDING_PROVIDER  = none | openai_compatible | openai

Local: `openai_compatible` covers every self-hosted server that speaks the
OpenAI chat API (llama.cpp llama-server, Ollama, vLLM, LM Studio, TGI).

Cloud: `anthropic` (Claude, official SDK — optional extra), `openai`
(api.openai.com), and `gemini` (Google Generative Language API) — the latter
two over plain HTTPS with no extra dependency. API keys come from
THESISLOGIC_GENERATION_API_KEY or each vendor's conventional variable
(ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY).

`none` runs ThesisLogic in fully deterministic mode with no model at all —
every workflow still works.
"""

from __future__ import annotations

import os

from ..config import Settings
from .base import EmbeddingProvider, GenerationProvider, GenerationResult
from .deterministic import DeterministicProvider
from .openai_compat import OpenAICompatEmbeddings, OpenAICompatProvider

_LOCAL_DEFAULTS = ("127.0.0.1", "localhost")

OPENAI_API_BASE = "https://api.openai.com"
OPENAI_DEFAULT_MODEL = "gpt-4o"
OPENAI_DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


def _cloud_base_url(configured: str, cloud_default: str) -> str:
    """Use the configured URL unless it is still the localhost default."""
    if any(host in configured for host in _LOCAL_DEFAULTS):
        return cloud_default
    return configured


def build_generation_provider(settings: Settings) -> GenerationProvider:
    kind = settings.generation_provider.lower()
    if kind in ("", "none", "deterministic"):
        return DeterministicProvider()
    if kind in ("openai_compatible", "local", "llama.cpp", "ollama", "vllm"):
        return OpenAICompatProvider(
            base_url=settings.generation_base_url,
            model=settings.generation_model,
            api_key=settings.generation_api_key,
            timeout=settings.generation_timeout_seconds,
        )
    if kind == "openai":
        return OpenAICompatProvider(
            base_url=_cloud_base_url(settings.generation_base_url, OPENAI_API_BASE),
            model=settings.generation_model or OPENAI_DEFAULT_MODEL,
            api_key=settings.generation_api_key or os.environ.get("OPENAI_API_KEY", ""),
            timeout=settings.generation_timeout_seconds,
        )
    if kind == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider(
            model=settings.generation_model,
            api_key=settings.generation_api_key,
            timeout=settings.generation_timeout_seconds,
        )
    if kind == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(
            model=settings.generation_model,
            api_key=settings.generation_api_key,
            timeout=settings.generation_timeout_seconds,
        )
    raise ValueError(f"unknown generation provider: {settings.generation_provider}")


def build_embedding_provider(settings: Settings) -> EmbeddingProvider | None:
    kind = settings.embedding_provider.lower()
    if kind in ("", "none"):
        return None
    if kind in ("openai_compatible", "local", "llama.cpp", "ollama"):
        return OpenAICompatEmbeddings(
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
            api_key=settings.embedding_api_key,
        )
    if kind == "openai":
        return OpenAICompatEmbeddings(
            base_url=_cloud_base_url(settings.embedding_base_url, OPENAI_API_BASE),
            model=settings.embedding_model or OPENAI_DEFAULT_EMBEDDING_MODEL,
            api_key=settings.embedding_api_key or os.environ.get("OPENAI_API_KEY", ""),
        )
    raise ValueError(f"unknown embedding provider: {settings.embedding_provider}")


__all__ = [
    "GenerationProvider", "GenerationResult", "EmbeddingProvider",
    "build_generation_provider", "build_embedding_provider",
]
