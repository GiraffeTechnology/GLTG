"""Provider-neutral LLM adapter interface for the GLTG evaluator.

GLTG is provider-agnostic. The orchestrator only ever talks to this interface;
concrete adapters (qwen, openai-compatible, anthropic, gemini, deepseek, local,
mock) hide differences in message format, JSON mode, tool/function calling,
response parsing, authentication, timeout/retry, and error classes.

Adapters return *normalized* content: a parsed ``dict`` representing the GLTG
assessment packet JSON, never a provider-native response envelope.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class ProviderError(Exception):
    """Base class for all provider adapter failures."""


class ProviderUnavailable(ProviderError):
    """Provider could not be reached / is not configured (no credentials, etc.)."""


class ProviderTimeout(ProviderError):
    """Provider did not respond within the configured timeout."""


class ProviderInvalidOutput(ProviderError):
    """Provider returned content that is not valid JSON / not schema-shaped."""


@runtime_checkable
class GLTGLLMProvider(Protocol):
    """Provider-neutral evaluator boundary.

    This is the core model boundary -- NOT ``qwen_client.evaluate(...)``.
    """

    provider_name: str

    def evaluate_gltg_assessment(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        schema: dict[str, Any],
        model: str,
        timeout_seconds: int,
        temperature: float = 0.0,
        json_mode: bool = True,
        repair: bool = False,
        previous_error: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate trade context and return a normalized assessment-packet dict.

        Raises:
            ProviderUnavailable: provider not configured or unreachable.
            ProviderTimeout: provider exceeded ``timeout_seconds``.
            ProviderInvalidOutput: provider returned non-JSON / unparseable output.
            ProviderError: any other provider-side failure.
        """
        ...


__all__ = [
    "GLTGLLMProvider",
    "ProviderError",
    "ProviderUnavailable",
    "ProviderTimeout",
    "ProviderInvalidOutput",
]
