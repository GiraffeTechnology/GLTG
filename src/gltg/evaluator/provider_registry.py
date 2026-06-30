"""Provider registry: resolve a provider name to a configured adapter.

This is where the provider-agnostic boundary is wired. The orchestrator asks the
registry for an adapter by name; unknown names fail with a clear error listing
the supported providers.
"""

from __future__ import annotations

from typing import Callable

from .config import EvaluatorSettings
from .providers.base import GLTGLLMProvider, ProviderError


def _build_qwen(settings: EvaluatorSettings) -> GLTGLLMProvider:
    from .providers.qwen import QwenProvider

    return QwenProvider(
        base_url=settings.base_url,
        api_key=settings.api_key,
        max_retries=settings.max_retries,
    )


def _build_openai_compatible(settings: EvaluatorSettings) -> GLTGLLMProvider:
    from .providers.openai_compatible import OpenAICompatibleProvider

    return OpenAICompatibleProvider(
        base_url=settings.base_url,
        api_key=settings.api_key,
        max_retries=settings.max_retries,
    )


def _build_anthropic(settings: EvaluatorSettings) -> GLTGLLMProvider:
    from .providers.anthropic import AnthropicProvider

    return AnthropicProvider(
        base_url=settings.base_url,
        api_key=settings.api_key,
        max_retries=settings.max_retries,
    )


def _build_gemini(settings: EvaluatorSettings) -> GLTGLLMProvider:
    from .providers.gemini import GeminiProvider

    return GeminiProvider(
        base_url=settings.base_url,
        api_key=settings.api_key,
        max_retries=settings.max_retries,
    )


def _build_deepseek(settings: EvaluatorSettings) -> GLTGLLMProvider:
    from .providers.deepseek import DeepSeekProvider

    return DeepSeekProvider(
        base_url=settings.base_url,
        api_key=settings.api_key,
        max_retries=settings.max_retries,
    )


def _build_local(settings: EvaluatorSettings) -> GLTGLLMProvider:
    from .providers.local import LocalProvider

    return LocalProvider(
        base_url=settings.base_url,
        api_key=settings.api_key,
        max_retries=settings.max_retries,
    )


def _build_mock(settings: EvaluatorSettings) -> GLTGLLMProvider:
    from .providers.mock import MockGLTGProvider

    return MockGLTGProvider(scenario=settings.mock_scenario, model=settings.model)


_REGISTRY: dict[str, Callable[[EvaluatorSettings], GLTGLLMProvider]] = {
    "qwen": _build_qwen,
    "openai_compatible": _build_openai_compatible,
    "anthropic": _build_anthropic,
    "gemini": _build_gemini,
    "deepseek": _build_deepseek,
    "local": _build_local,
    "mock": _build_mock,
}

SUPPORTED_PROVIDERS = tuple(sorted(_REGISTRY))


def get_provider(settings: EvaluatorSettings) -> GLTGLLMProvider:
    """Return a configured provider adapter for ``settings.provider``.

    In ``mock`` evaluator mode the mock provider is always used regardless of the
    configured provider, so CI never reaches a real network backend.
    """

    name = "mock" if settings.evaluator_mode == "mock" else settings.provider
    builder = _REGISTRY.get(name)
    if builder is None:
        raise ProviderError(
            f"Unknown GLTG_LLM_PROVIDER '{settings.provider}'. "
            f"Supported providers: {', '.join(SUPPORTED_PROVIDERS)}."
        )
    return builder(settings)


__all__ = ["get_provider", "SUPPORTED_PROVIDERS"]
