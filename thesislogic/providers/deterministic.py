from __future__ import annotations

from .base import GenerationResult


class DeterministicProvider:
    """No-model mode: workflows return only their deterministic output.

    This is a first-class posture, not a degraded one — some firms and courts
    require that no generative model touch case material. Every workflow in
    ThesisLogic produces a complete deterministic answer without a model.
    """

    name = "none"

    def generate(self, system: str, prompt: str, max_tokens: int = 1600) -> GenerationResult:
        return GenerationResult(text="", provider=self.name, model="", live=False,
                                error="generation disabled (provider=none)")

    def health(self) -> dict:
        return {"provider": self.name, "ready": True,
                "detail": "deterministic mode; no model configured"}
