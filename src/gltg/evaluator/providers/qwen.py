"""Qwen default reference adapter.

Qwen3.5 is the default *bundled/reference* evaluator backend for the first GLTG
implementation. Giraffe is NOT a Qwen ecosystem product: this adapter is just
one implementation of the provider-neutral interface. Qwen exposes an
OpenAI-compatible endpoint (DashScope compatible mode), so the default adapter
reuses the OpenAI-compatible transport with Qwen defaults.
"""

from __future__ import annotations

from .openai_compatible import OpenAICompatibleProvider


class QwenProvider(OpenAICompatibleProvider):
    provider_name = "qwen"
    # DashScope OpenAI-compatible endpoint; override via GLTG_LLM_BASE_URL.
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

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
            provider_name="qwen",
        )


__all__ = ["QwenProvider"]
