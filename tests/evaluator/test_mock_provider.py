"""Mock-provider evaluator scenarios (§18.1)."""

from __future__ import annotations

import pytest

from gltg.evaluator import evaluate
from gltg.evaluator.schemas import GLTGAssessmentPacket


def _codes(res) -> set[str]:
    return {w.code for w in res.warnings}


def test_valid_packet_passes(make_request):
    res = evaluate(make_request())
    assert res.ok is True
    assert res.evaluation_mode == "llm"
    assert res.model_provider == "mock"
    assert res.assessment_schema_version == "gltg-assessment-v1"
    assert res.manual_review_required is False
    # Packet round-trips through the typed schema.
    packet = GLTGAssessmentPacket.model_validate(res.assessment_packet)
    assert packet.lead_time_risk_assessment.p50_days <= packet.lead_time_risk_assessment.p80_days


def test_invalid_json_triggers_manual_review(make_request, monkeypatch):
    monkeypatch.setenv("GLTG_MOCK_SCENARIO", "invalid_json")
    res = evaluate(make_request())
    assert res.manual_review_required is True
    assert "EVALUATOR_UNAVAILABLE" in _codes(res)


def test_schema_invalid_triggers_manual_review(make_request, monkeypatch):
    monkeypatch.setenv("GLTG_MOCK_SCENARIO", "schema_invalid")
    res = evaluate(make_request())
    assert res.manual_review_required is True
    assert "EVALUATOR_UNAVAILABLE" in _codes(res)


def test_timeout_triggers_manual_review_without_fallback(make_request, monkeypatch):
    monkeypatch.setenv("GLTG_MOCK_SCENARIO", "timeout")
    res = evaluate(make_request())
    assert res.manual_review_required is True
    assert res.evaluation_mode == "llm"
    assert "EVALUATOR_UNAVAILABLE" in _codes(res)


def test_timeout_uses_fallback_when_allowed(make_request, monkeypatch):
    monkeypatch.setenv("GLTG_MOCK_SCENARIO", "timeout")
    monkeypatch.setenv("GLTG_ALLOW_RULE_FALLBACK", "true")
    res = evaluate(make_request())
    assert res.evaluation_mode == "fallback"
    assert "LLM_PROVIDER_UNAVAILABLE_RULE_FALLBACK_USED" in _codes(res)


def test_confirmed_without_evidence_is_downgraded(make_request, monkeypatch):
    monkeypatch.setenv("GLTG_MOCK_SCENARIO", "confirmed_without_evidence")
    res = evaluate(make_request())
    se = res.assessment_packet["supplier_execution_assessment"]
    assert se["status"] != "confirmed"
    assert se["confidence"] < 0.8
    assert "CONFIRMED_WITHOUT_EVIDENCE_DOWNGRADED" in _codes(res)


def test_p90_less_than_p80_is_repaired(make_request, monkeypatch):
    monkeypatch.setenv("GLTG_MOCK_SCENARIO", "p90_lt_p80")
    res = evaluate(make_request())
    q = res.quantiles
    assert q.p50_days <= q.p80_days <= q.p90_days
    assert res.assessment_packet["audit"]["repaired"] is True


def test_high_confidence_unknown_material_is_downgraded(make_request, monkeypatch):
    monkeypatch.setenv("GLTG_MOCK_SCENARIO", "high_confidence_unknown_material")
    res = evaluate(make_request())
    qc = res.assessment_packet["quote_confidence_assessment"]
    assert qc["quote_confidence_level"] != "high"
    assert qc["confidence_score"] < 0.8
    assert "HIGH_CONFIDENCE_WITHOUT_EVIDENCE_DOWNGRADED" in _codes(res)


@pytest.mark.parametrize("scenario", ["valid", "p90_lt_p80", "confirmed_without_evidence"])
def test_quantiles_are_always_monotonic(make_request, monkeypatch, scenario):
    monkeypatch.setenv("GLTG_MOCK_SCENARIO", scenario)
    res = evaluate(make_request())
    assert res.quantiles.p50_days <= res.quantiles.p80_days <= res.quantiles.p90_days
    assert res.quantiles.p50_days > 0
