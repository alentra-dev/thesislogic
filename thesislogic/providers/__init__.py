"""AI provider abstraction.

A firm chooses its posture with two environment variables:

    THESISLOGIC_GENERATION_PROVIDER = none | openai_compatible | anthropic
    THESISLOGIC_EMBEDDING_PROVIDER  = none | openai_compatible

`openai_compatible` covers every local server that speaks the OpenAI chat API
(llama.cpp llama-server, Ollama, vLLM, LM Studio, TGI) as well as hosted
OpenAI-compatible endpoints. `anthropic` uses the official Anthropic SDK for
firms that prefer Claude via cloud API. `none` runs ThesisLogic in fully
deterministic mode with no model at all — every workflow still works.
"""

from __future__ import annotations

from ..config import Settings
from .base import EmbeddingProvider, GenerationProvider, GenerationResult
from .deterministic import DeterministicProvider
from .openai_compat import OpenAICompatEmbeddings, OpenAICompatProvider


def build_generation_provider(settings: Settings) -> GenerationProvider:
    kind = settings.generation_provider.lower()
    if kind in ("", "none", "deterministic"):
        return DeterministicProvider()
    if kind in ("openai_compatible", "openai", "local", "llama.cpp", "ollama", "vllm"):
        return OpenAICompatProvider(
            base_url=settings.generation_base_url,
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
    if kind in ("openai_compatible", "openai", "local", "llama.cpp", "ollama"):
        return OpenAICompatEmbeddings(
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
            api_key=settings.embedding_api_key,
        )
    raise ValueError(f"unknown embedding provider: {settings.embedding_provider}")


__all__ = [
    "GenerationProvider", "GenerationResult", "EmbeddingProvider",
    "build_generation_provider", "build_embedding_provider",
]
