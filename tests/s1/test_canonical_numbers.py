from __future__ import annotations

import importlib

import pytest

from gltg.evaluator import evaluate
from gltg.evaluator.providers.base import ProviderUnavailable
from gltg.evaluator.providers.mock import MockGLTGProvider
from tests.evaluator.conftest import load_request

orchestrator_module = importlib.import_module("gltg.evaluator.orchestrator")


class PoisonedNumericalProvider(MockGLTGProvider):
    def __init__(self, provider_name: str) -> None:
        super().__init__()
        self.provider_name = provider_name

    def evaluate_gltg_assessment(self, **kwargs):
        packet = super().evaluate_gltg_assessment(**kwargs)
        packet["lead_time_risk_assessment"].update(
            {"p50_days": 999.0, "p80_days": 1.0, "p90_days": -50.0}
        )
        return packet


class UnavailableProvider(MockGLTGProvider):
    provider_name = "unavailable-provider"

    def evaluate_gltg_assessment(self, **kwargs):
        raise ProviderUnavailable("provider unavailable; raw body must not escape")


def _canonical_numbers(response) -> dict:
    return {
        "run_id": response.gltg_run_id,
        "model_version": response.model_version,
        "rule_version": response.rule_version,
        "calibration_version": response.calibration_version,
        "quantiles": response.quantiles.model_dump(),
        "components": response.components.model_dump(),
        "selected_confidence_days": response.risk.selected_confidence_days,
        "deadline_feasible": response.risk.deadline_feasible,
    }


def test_llm_qwen_non_qwen_and_off_have_identical_canonical_numbers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = load_request()
    monkeypatch.setenv("GLTG_EVALUATOR_MODE", "deterministic")
    deterministic = evaluate(request)

    variants = []
    for provider_name in ("qwen", "openai_compatible"):
        monkeypatch.setenv("GLTG_EVALUATOR_MODE", "llm")
        monkeypatch.setenv("GLTG_LLM_PROVIDER", provider_name)
        monkeypatch.setattr(
            orchestrator_module,
            "get_provider",
            lambda settings, name=provider_name: PoisonedNumericalProvider(name),
        )
        variants.append(evaluate(request))

    assert all(
        _canonical_numbers(result) == _canonical_numbers(deterministic)
        for result in variants
    )
    for result in variants:
        assert result.assessment_packet["lead_time_risk_assessment"]["p50_days"] != 999.0
        assert "raw_provider_body" not in result.model_dump_json()


def test_unavailable_llm_is_explicit_but_numbers_remain_canonical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = load_request()
    monkeypatch.setenv("GLTG_EVALUATOR_MODE", "deterministic")
    deterministic = evaluate(request)
    monkeypatch.setenv("GLTG_EVALUATOR_MODE", "llm")
    monkeypatch.setattr(orchestrator_module, "get_provider", lambda settings: UnavailableProvider())

    result = evaluate(request)

    assert _canonical_numbers(result) == _canonical_numbers(deterministic)
    assert any(w.code == "EVALUATOR_UNAVAILABLE" for w in result.warnings)
    assert result.manual_review_required is True
    assert "raw body" not in result.model_dump_json()


def test_explicit_versions_and_input_produce_stable_complete_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GLTG_EVALUATOR_MODE", "deterministic")
    request = load_request()
    first = evaluate(request).model_dump(mode="json")
    second = evaluate(request).model_dump(mode="json")
    assert first == second
