from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class GenerationResult:
    text: str
    provider: str
    model: str
    live: bool                      # True when a real model produced the text
    error: str = ""
    usage: dict = field(default_factory=dict)


@runtime_checkable
class GenerationProvider(Protocol):
    name: str

    def generate(self, system: str, prompt: str, max_tokens: int = 1600) -> GenerationResult:
        """Produce a completion. Must never raise; report failures in .error."""
        ...

    def health(self) -> dict:
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        """Return one vector per text, or None on failure (callers fall back to lexical)."""
        ...

    def health(self) -> dict:
        ...
