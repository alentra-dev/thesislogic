"""Environment-driven configuration.

Every deployment knob is an environment variable prefixed with THESISLOGIC_.
Firms deploying on-premises set these in a systemd EnvironmentFile or .env;
cloud deployments set them in their orchestrator.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(f"THESISLOGIC_{name}", default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name, "true" if default else "false").lower()
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = _env(name, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Settings:
    # Storage
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "./data")).resolve())
    packs_dir: Path = field(default_factory=lambda: Path(_env("PACKS_DIR", "./packs")).resolve())
    active_pack: str = field(default_factory=lambda: _env("ACTIVE_PACK", ""))

    # Server
    host: str = field(default_factory=lambda: _env("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8600))

    # AI generation provider: "none" | "openai_compatible" | "anthropic"
    generation_provider: str = field(default_factory=lambda: _env("GENERATION_PROVIDER", "none"))
    generation_base_url: str = field(default_factory=lambda: _env("GENERATION_BASE_URL", "http://127.0.0.1:8080"))
    generation_model: str = field(default_factory=lambda: _env("GENERATION_MODEL", ""))
    generation_api_key: str = field(default_factory=lambda: _env("GENERATION_API_KEY", ""))
    generation_max_tokens: int = field(default_factory=lambda: _env_int("GENERATION_MAX_TOKENS", 1600))
    # Character budget for the evidence section of generation prompts. Local
    # servers often run small per-slot context windows; the prompt builder
    # trims spans to fit rather than triggering a backend 400.
    generation_prompt_budget: int = field(default_factory=lambda: _env_int("GENERATION_PROMPT_BUDGET", 7000))
    # One corrective retry when the proof gate rejects a live draft.
    generation_gate_retries: int = field(default_factory=lambda: _env_int("GENERATION_GATE_RETRIES", 1))
    generation_timeout_seconds: int = field(default_factory=lambda: _env_int("GENERATION_TIMEOUT_SECONDS", 180))
    # Proof-gate posture: when false, live model output is recorded as a shadow
    # preview only and the deterministic answer is always returned.
    prefer_live_output: bool = field(default_factory=lambda: _env_bool("PREFER_LIVE_OUTPUT", True))

    # Embeddings (optional; lexical-only retrieval works without them):
    # "none" | "openai_compatible"
    embedding_provider: str = field(default_factory=lambda: _env("EMBEDDING_PROVIDER", "none"))
    embedding_base_url: str = field(default_factory=lambda: _env("EMBEDDING_BASE_URL", "http://127.0.0.1:8092"))
    embedding_model: str = field(default_factory=lambda: _env("EMBEDDING_MODEL", ""))
    embedding_api_key: str = field(default_factory=lambda: _env("EMBEDDING_API_KEY", ""))

    # Auth
    allow_registration: bool = field(default_factory=lambda: _env_bool("ALLOW_REGISTRATION", True))
    session_ttl_seconds: int = field(default_factory=lambda: _env_int("SESSION_TTL_SECONDS", 8 * 3600))
    lockout_threshold: int = field(default_factory=lambda: _env_int("LOCKOUT_THRESHOLD", 5))
    lockout_seconds: int = field(default_factory=lambda: _env_int("LOCKOUT_SECONDS", 300))

    # Firm identity (shown in the UI and exports)
    firm_name: str = field(default_factory=lambda: _env("FIRM_NAME", "Your Firm"))

    def ensure_dirs(self) -> None:
        (self.data_dir / "uploads").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "audit").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "index").mkdir(parents=True, exist_ok=True)
        self.packs_dir.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    global _settings
    if _settings is None or reload:
        _settings = Settings()
    return _settings
