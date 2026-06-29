"""
GLTG -> aivan integration client.
Triggers per-enquiry dynamic questionnaires via aivan's POST /invoke endpoint.
LLM extraction: local vLLM primary, DashScope/Qwen fallback.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

AIVAN_BASE_URL = os.getenv("AIVAN_BASE_URL", "http://localhost:8765")
AIVAN_TIMEOUT = float(os.getenv("AIVAN_TIMEOUT", "30"))


class AivanClient:
    """Thin HTTP client for aivan skill invocation."""

    def __init__(self, base_url: str = AIVAN_BASE_URL, timeout: float = AIVAN_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def trigger_questionnaire(
        self,
        session_id: str,
        enquiry_context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Trigger a supplier signal questionnaire for a given enquiry.
        Returns aivan's response envelope: {"status": "ok"|"error", "output": str, ...}
        Raises httpx.HTTPError on network failure.
        """
        payload = {
            "session_id": session_id,
            "user_input": "__questionnaire_trigger__",
            "context": enquiry_context,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/invoke", json=payload)
            resp.raise_for_status()
            return resp.json()
