"""Local / private enterprise model adapter.

Local model servers (vLLM, Ollama's OpenAI-compatible mode, LM Studio, TGI with
an OpenAI shim, and most private enterprise gateways) speak the OpenAI-compatible
chat-completions protocol. This adapter targets such an endpoint and does not
require an API key by default (``GLTG_LLM_BASE_URL`` is required).
"""

from __future__ import annotations

from typing import Any

from .base import ProviderUnavailable
from .openai_compatible import OpenAICompatibleProvider


class LocalProvider(OpenAICompatibleProvider):
    provider_name = "local"
    default_base_url = "http://localhost:8000/v1"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        max_retries: int = 2,
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key=api_key or "not-required",
            max_retries=max_retries,
            provider_name="local",
        )

    def evaluate_gltg_assessment(self, **kwargs: Any) -> dict[str, Any]:
        if not self.base_url:
            raise ProviderUnavailable("local: GLTG_LLM_BASE_URL must point at the local model server")
        return super().evaluate_gltg_assessment(**kwargs)


__all__ = ["LocalProvider"]
