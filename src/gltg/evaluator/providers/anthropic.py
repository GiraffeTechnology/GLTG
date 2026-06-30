"""Anthropic / Claude-compatible adapter.

Uses the Anthropic Messages API shape (``/v1/messages``). The adapter normalizes
the Claude-native response into a parsed assessment-packet dict, hiding the
provider-specific message and content-block format from GLTG business logic.
"""

from __future__ import annotations

import json
from typing import Any

from .base import (
    ProviderError,
    ProviderInvalidOutput,
    ProviderTimeout,
    ProviderUnavailable,
)
from .openai_compatible import _loads_json


class AnthropicProvider:
    provider_name = "anthropic"
    default_base_url = "https://api.anthropic.com/v1"
    anthropic_version = "2023-06-01"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        max_retries: int = 2,
    ) -> None:
        self.base_url = (base_url or self.default_base_url).rstrip("/")
        self.api_key = api_key
        self.max_retries = max_retries

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
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise ProviderUnavailable("httpx is required for HTTP providers") from exc
        if not self.api_key:
            raise ProviderUnavailable("anthropic: missing API key (set GLTG_LLM_API_KEY)")

        user_content: dict[str, Any] = {
            "instruction": "Evaluate the trade context and return a GLTG assessment packet as JSON.",
            "schema": schema,
            "input": user_payload,
        }
        if repair and previous_error:
            user_content["repair_instruction"] = (
                f"Previous output was rejected ({previous_error}); return valid JSON only."
            )
        body = {
            "model": model,
            "max_tokens": 4096,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": json.dumps(user_content, ensure_ascii=False)}
            ],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.anthropic_version,
            "content-type": "application/json",
        }
        url = f"{self.base_url}/messages"
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                resp = client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("anthropic: request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"anthropic: transport error: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(f"anthropic: HTTP {resp.status_code}: {resp.text[:200]}")
        return self._parse_response(resp.json())

    def _parse_response(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            blocks = data["content"]
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (KeyError, TypeError, AttributeError) as exc:
            raise ProviderInvalidOutput("anthropic: unexpected response envelope") from exc
        return _loads_json(text, self.provider_name)


__all__ = ["AnthropicProvider"]
