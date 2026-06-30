"""Gemini-compatible adapter.

Uses the Google Generative Language ``generateContent`` endpoint shape and
normalizes the Gemini-native response into a parsed assessment-packet dict.
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


class GeminiProvider:
    provider_name = "gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"

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
            raise ProviderUnavailable("gemini: missing API key (set GLTG_LLM_API_KEY)")

        user_content: dict[str, Any] = {
            "instruction": "Evaluate the trade context and return a GLTG assessment packet as JSON.",
            "schema": schema,
            "input": user_payload,
        }
        if repair and previous_error:
            user_content["repair_instruction"] = (
                f"Previous output was rejected ({previous_error}); return valid JSON only."
            )
        generation_config: dict[str, Any] = {"temperature": temperature}
        if json_mode:
            generation_config["responseMimeType"] = "application/json"
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [
                {"role": "user", "parts": [{"text": json.dumps(user_content, ensure_ascii=False)}]}
            ],
            "generationConfig": generation_config,
        }
        url = f"{self.base_url}/models/{model}:generateContent?key={self.api_key}"
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                resp = client.post(url, json=body, headers={"content-type": "application/json"})
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("gemini: request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"gemini: transport error: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(f"gemini: HTTP {resp.status_code}: {resp.text[:200]}")
        return self._parse_response(resp.json())

    def _parse_response(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ProviderInvalidOutput("gemini: unexpected response envelope") from exc
        return _loads_json(text, self.provider_name)


__all__ = ["GeminiProvider"]
