"""Cloud provider using the official Anthropic SDK.

Install with: pip install "thesislogic[anthropic]"
Configure:
    THESISLOGIC_GENERATION_PROVIDER=anthropic
    THESISLOGIC_GENERATION_MODEL=claude-opus-4-8   (default)
    ANTHROPIC_API_KEY=...  (or THESISLOGIC_GENERATION_API_KEY)
"""

from __future__ import annotations

from .base import GenerationResult

DEFAULT_MODEL = "claude-opus-4-8"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str = "", api_key: str = "", timeout: int = 180):
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "the anthropic SDK is not installed; run: pip install 'thesislogic[anthropic]'"
            ) from exc
        kwargs: dict = {"timeout": float(timeout)}
        if api_key:
            kwargs["api_key"] = api_key
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(**kwargs)
        self.model = model or DEFAULT_MODEL

    def generate(self, system: str, prompt: str, max_tokens: int = 1600) -> GenerationResult:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            if response.stop_reason == "refusal":
                return GenerationResult(text="", provider=self.name, model=self.model,
                                        live=False, error="model refused the request")
            text = "".join(block.text for block in response.content if block.type == "text")
            usage = {"input_tokens": response.usage.input_tokens,
                     "output_tokens": response.usage.output_tokens}
            return GenerationResult(text=text.strip(), provider=self.name,
                                    model=response.model, live=bool(text.strip()), usage=usage)
        except self._anthropic.APIError as exc:
            return GenerationResult(text="", provider=self.name, model=self.model,
                                    live=False, error=f"{type(exc).__name__}: {exc}")

    def health(self) -> dict:
        try:
            model = self.client.models.retrieve(self.model)
            return {"provider": self.name, "ready": True, "configured_model": self.model,
                    "display_name": model.display_name}
        except self._anthropic.APIError as exc:
            return {"provider": self.name, "ready": False, "configured_model": self.model,
                    "detail": f"{type(exc).__name__}: {exc}"}
