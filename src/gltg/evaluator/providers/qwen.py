"""Qwen cloud (DashScope) adapter.

One implementation of the provider-neutral interface for callers who use
Qwen's hosted DashScope endpoint. Giraffe is NOT a Qwen ecosystem product,
and this adapter is not the default: the default reference model
(``qwen3.5-9b-int4``) is served through the ``local`` provider from a
self-hosted OpenAI-compatible endpoint, with no external ecosystem
dependency. Qwen exposes an OpenAI-compatible endpoint (DashScope compatible
mode), so this adapter reuses the OpenAI-compatible transport.
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
