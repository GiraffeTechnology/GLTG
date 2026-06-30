"""Configuration for the GLTG provider-agnostic LLM-assisted evaluator.

All settings are read from environment variables at evaluation time so that the
service can be reconfigured (and tests can monkeypatch) without restarting the
process. Qwen3.5 is the default *reference* backend, but GLTG stays
provider-agnostic: nothing in the business logic depends on Qwen specifics.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

EvaluatorMode = Literal["llm", "fallback", "mock"]

DEFAULT_EVALUATOR_MODE = "llm"
DEFAULT_PROVIDER = "qwen"
DEFAULT_MODEL = "qwen3.5"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class EvaluatorSettings:
    """Resolved evaluator configuration for a single evaluation."""

    evaluator_mode: str = DEFAULT_EVALUATOR_MODE
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: int = 30
    max_retries: int = 2
    temperature: float = 0.0
    json_mode: bool = True
    strict_schema: bool = True
    allow_rule_fallback: bool = False
    # Mock-only knob used by deterministic CI tests.
    mock_scenario: str = "valid"

    @property
    def is_fallback_mode(self) -> bool:
        return self.evaluator_mode == "fallback"


def load_settings() -> EvaluatorSettings:
    """Build :class:`EvaluatorSettings` from the current environment."""

    return EvaluatorSettings(
        evaluator_mode=os.environ.get("GLTG_EVALUATOR_MODE", DEFAULT_EVALUATOR_MODE).strip().lower(),
        provider=os.environ.get("GLTG_LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower(),
        model=os.environ.get("GLTG_LLM_MODEL", DEFAULT_MODEL).strip(),
        base_url=os.environ.get("GLTG_LLM_BASE_URL") or None,
        api_key=os.environ.get("GLTG_LLM_API_KEY") or None,
        timeout_seconds=_env_int("GLTG_LLM_TIMEOUT_SECONDS", 30),
        max_retries=_env_int("GLTG_LLM_MAX_RETRIES", 2),
        temperature=_env_float("GLTG_LLM_TEMPERATURE", 0.0),
        json_mode=_env_bool("GLTG_LLM_JSON_MODE", True),
        strict_schema=_env_bool("GLTG_LLM_STRICT_SCHEMA", True),
        allow_rule_fallback=_env_bool("GLTG_ALLOW_RULE_FALLBACK", False),
        mock_scenario=os.environ.get("GLTG_MOCK_SCENARIO", "valid").strip().lower(),
    )
