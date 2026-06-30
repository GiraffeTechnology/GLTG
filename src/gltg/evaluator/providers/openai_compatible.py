"""OpenAI-compatible chat-completions adapter.

Many hosted and private models (including OpenAI itself, and a large fraction of
self-hosted enterprise deployments) expose an OpenAI-compatible
``/chat/completions`` endpoint. This adapter is the workhorse that several other
providers (qwen, deepseek, local) reuse by pointing at a different base URL.
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


class OpenAICompatibleProvider:
    provider_name = "openai_compatible"
    default_base_url = "https://api.openai.com/v1"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        max_retries: int = 2,
        provider_name: str | None = None,
    ) -> None:
        self.base_url = (base_url or self.default_base_url).rstrip("/")
        self.api_key = api_key
        self.max_retries = max_retries
        if provider_name:
            self.provider_name = provider_name

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
            raise ProviderUnavailable(
                f"{self.provider_name}: missing API key (set GLTG_LLM_API_KEY)"
            )

        body = self._build_request_body(
            system_prompt=system_prompt,
            user_payload=user_payload,
            schema=schema,
            model=model,
            temperature=temperature,
            json_mode=json_mode,
            repair=repair,
            previous_error=previous_error,
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=timeout_seconds) as client:
                    resp = client.post(url, json=body, headers=headers)
            except httpx.TimeoutException as exc:
                raise ProviderTimeout(f"{self.provider_name}: request timed out") from exc
            except httpx.HTTPError as exc:
                last_exc = exc
                continue
            if resp.status_code >= 500:
                last_exc = ProviderError(f"{self.provider_name}: HTTP {resp.status_code}")
                continue
            if resp.status_code >= 400:
                raise ProviderError(
                    f"{self.provider_name}: HTTP {resp.status_code}: {resp.text[:200]}"
                )
            return self._parse_response(resp.json())

        raise ProviderUnavailable(
            f"{self.provider_name}: exhausted retries"
        ) from last_exc

    def _build_request_body(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        schema: dict[str, Any],
        model: str,
        temperature: float,
        json_mode: bool,
        repair: bool,
        previous_error: str | None,
    ) -> dict[str, Any]:
        user_content = {
            "instruction": "Evaluate the trade context and return a GLTG assessment packet.",
            "schema": schema,
            "input": user_payload,
        }
        if repair and previous_error:
            user_content["repair_instruction"] = (
                "Your previous output was rejected. Fix it and return valid JSON "
                f"that conforms exactly to the schema. Error: {previous_error}"
            )
        body: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_content, ensure_ascii=False)},
            ],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    def _parse_response(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderInvalidOutput(
                f"{self.provider_name}: unexpected response envelope"
            ) from exc
        return _loads_json(content, self.provider_name)


def _loads_json(content: Any, provider_name: str) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise ProviderInvalidOutput(f"{provider_name}: non-string content")
    text = content.strip()
    # Tolerate fenced code blocks some models still emit.
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[: -3]
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProviderInvalidOutput(f"{provider_name}: content is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ProviderInvalidOutput(f"{provider_name}: JSON content is not an object")
    return parsed


__all__ = ["OpenAICompatibleProvider", "_loads_json"]
