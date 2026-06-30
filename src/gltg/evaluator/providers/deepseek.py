"""DeepSeek-compatible adapter.

DeepSeek exposes an OpenAI-compatible chat-completions endpoint, so this adapter
reuses the OpenAI-compatible transport with DeepSeek defaults.
"""

from __future__ import annotations

from .openai_compatible import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    provider_name = "deepseek"
    default_base_url = "https://api.deepseek.com/v1"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        max_retries: int = 2,
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            max_retries=max_retries,
            provider_name="deepseek",
        )


__all__ = ["DeepSeekProvider"]
