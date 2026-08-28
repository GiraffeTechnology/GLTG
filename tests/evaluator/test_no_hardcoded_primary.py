"""Prove deterministic simulation is always the canonical numerical boundary."""

from __future__ import annotations

import gltg.evaluator.fallback_rules as fallback_rules
from gltg.evaluator import evaluate


def _spy_on_simulator(monkeypatch):
    calls = {"count": 0}
    original = fallback_rules._simulator.simulate

    def _counting(req):
        calls["count"] += 1
        return original(req)

    monkeypatch.setattr(fallback_rules._simulator, "simulate", _counting)
    return calls


def test_default_llm_path_calls_rule_simulator_for_canonical_numbers(make_request, monkeypatch):
    # autouse fixture already pins llm + mock provider.
    calls = _spy_on_simulator(monkeypatch)
    res = evaluate(make_request())
    assert res.evaluation_mode == "deterministic_with_llm_auxiliary"
    assert res.model_provider == "deterministic_rules"
    assert calls["count"] == 1


def test_rule_simulator_used_only_in_fallback_mode(make_request, monkeypatch):
    calls = _spy_on_simulator(monkeypatch)
    monkeypatch.setenv("GLTG_EVALUATOR_MODE", "fallback")
    res = evaluate(make_request())
    assert res.evaluation_mode == "fallback"
    assert calls["count"] == 1


def test_rule_simulator_used_when_provider_fails_and_legacy_fallback_allowed(
    make_request, monkeypatch
):
    calls = _spy_on_simulator(monkeypatch)
    monkeypatch.setenv("GLTG_MOCK_SCENARIO", "timeout")
    monkeypatch.setenv("GLTG_ALLOW_RULE_FALLBACK", "true")
    res = evaluate(make_request())
    assert res.evaluation_mode == "deterministic_with_llm_unavailable"
    assert calls["count"] == 1


def test_rule_simulator_still_anchors_numbers_when_provider_fails(make_request, monkeypatch):
    calls = _spy_on_simulator(monkeypatch)
    monkeypatch.setenv("GLTG_MOCK_SCENARIO", "timeout")
    res = evaluate(make_request())
    assert res.manual_review_required is True
    assert calls["count"] == 1
