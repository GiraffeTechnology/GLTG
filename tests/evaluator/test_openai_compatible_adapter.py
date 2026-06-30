"""HTTP adapter tests for the OpenAI-compatible transport (no real network).

Uses respx to mock the HTTP boundary so the adapter parsing/normalization and
the end-to-end orchestrator path with a non-mock provider are exercised in CI.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from gltg.evaluator import evaluate
from gltg.evaluator.providers.base import ProviderTimeout, ProviderUnavailable
from gltg.evaluator.providers.openai_compatible import OpenAICompatibleProvider

BASE_URL = "https://example-llm.test/v1"


def _valid_packet_content() -> str:
    return json.dumps(
        {
            "assessment_schema_version": "gltg-assessment-v1",
            "model_provider": "openai_compatible",
            "model_name": "test-model",
            "evaluation_mode": "llm",
            "material_availability_assessment": {
                "material_availability_status": "in_stock",
                "status": "inferred",
                "confidence": 0.6,
                "evidence_refs": ["GDB_SYN_V1_OBS_000001"],
            },
            "lead_time_risk_assessment": {
                "p50_days": 30,
                "p80_days": 38,
                "p90_days": 45,
                "deadline_risk_level": "low",
                "evidence_refs": ["GDB_SYN_V1_OBS_000001"],
            },
            "evidence_refs": ["GDB_SYN_V1_OBS_000001"],
        }
    )


def test_missing_api_key_raises_unavailable():
    provider = OpenAICompatibleProvider(base_url=BASE_URL, api_key=None)
    with pytest.raises(ProviderUnavailable):
        provider.evaluate_gltg_assessment(
            system_prompt="s",
            user_payload={},
            schema={},
            model="test-model",
            timeout_seconds=5,
        )


@respx.mock
def test_adapter_parses_chat_completion():
    respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": _valid_packet_content()}}]},
        )
    )
    provider = OpenAICompatibleProvider(base_url=BASE_URL, api_key="secret")
    out = provider.evaluate_gltg_assessment(
        system_prompt="s",
        user_payload={"hello": "world"},
        schema={},
        model="test-model",
        timeout_seconds=5,
    )
    assert out["lead_time_risk_assessment"]["p50_days"] == 30


@respx.mock
def test_adapter_timeout_maps_to_provider_timeout():
    respx.post(f"{BASE_URL}/chat/completions").mock(side_effect=httpx.TimeoutException("t"))
    provider = OpenAICompatibleProvider(base_url=BASE_URL, api_key="secret")
    with pytest.raises(ProviderTimeout):
        provider.evaluate_gltg_assessment(
            system_prompt="s",
            user_payload={},
            schema={},
            model="test-model",
            timeout_seconds=1,
        )


@respx.mock
def test_orchestrator_end_to_end_with_openai_compatible(make_request, monkeypatch):
    monkeypatch.setenv("GLTG_EVALUATOR_MODE", "llm")
    monkeypatch.setenv("GLTG_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("GLTG_LLM_BASE_URL", BASE_URL)
    monkeypatch.setenv("GLTG_LLM_API_KEY", "secret")
    respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": _valid_packet_content()}}]},
        )
    )
    res = evaluate(make_request())
    assert res.evaluation_mode == "llm"
    assert res.model_provider == "openai_compatible"
    assert res.quantiles.p50_days <= res.quantiles.p80_days <= res.quantiles.p90_days
