"""Validator, guardrail, and quantile-normalizer unit tests (§12, §13)."""

from __future__ import annotations

from gltg.evaluator.guardrails import apply_business_guardrails, normalize_quantiles
from gltg.evaluator.schemas import GLTGAssessmentPacket
from gltg.evaluator.validator import validate_and_repair


def _packet(**lt) -> GLTGAssessmentPacket:
    packet = GLTGAssessmentPacket()
    for key, value in lt.items():
        setattr(packet.lead_time_risk_assessment, key, value)
    return packet


def test_quantiles_repaired_when_out_of_order(make_request):
    packet = _packet(p50_days=30, p80_days=20, p90_days=10)
    notes = normalize_quantiles(packet, make_request())
    lt = packet.lead_time_risk_assessment
    assert lt.p50_days <= lt.p80_days <= lt.p90_days
    assert any("repaired" in n for n in notes)


def test_tail_widens_for_unknown_material(make_request):
    base = _packet(p50_days=30, p80_days=33, p90_days=36)
    base.material_availability_assessment.material_availability_status = "in_stock"
    normalize_quantiles(base, make_request())
    narrow_p90 = base.lead_time_risk_assessment.p90_days

    wide = _packet(p50_days=30, p80_days=33, p90_days=36)
    wide.material_availability_assessment.material_availability_status = (
        "supplier_confirmation_required"
    )
    normalize_quantiles(wide, make_request())
    assert wide.lead_time_risk_assessment.p90_days > narrow_p90


def test_confirmed_without_evidence_downgraded(make_request):
    packet = GLTGAssessmentPacket()
    packet.supplier_execution_assessment.status = "confirmed"
    packet.supplier_execution_assessment.evidence_refs = []
    result = validate_and_repair(packet, make_request())
    assert packet.supplier_execution_assessment.status == "needs_confirmation"
    assert any(w.code == "CONFIRMED_WITHOUT_EVIDENCE_DOWNGRADED" for w in result.warnings)


def test_unknown_material_cannot_be_confirmed(make_request):
    packet = GLTGAssessmentPacket()
    packet.material_availability_assessment.material_availability_status = "unknown"
    packet.material_availability_assessment.status = "confirmed"
    packet.material_availability_assessment.evidence_refs = ["GDB_SYN_V1_OBS_000001"]
    result = validate_and_repair(packet, make_request())
    assert packet.material_availability_assessment.status != "confirmed"
    assert any(w.code == "UNKNOWN_MATERIAL_CANNOT_BE_CONFIRMED" for w in result.warnings)


def test_fast_unsupported_quote_triggers_manual_review(make_request):
    req = make_request(
        trade_processing_factors={
            "material": {"material_availability_status": "unknown"},
            "behavior": {"unsupported_precise_leadtime_signal": True},
        }
    )
    packet = GLTGAssessmentPacket()
    packet.material_availability_assessment.material_availability_status = "unknown"
    packet.material_availability_assessment.evidence_refs = []
    packet.quote_confidence_assessment.confidence_score = 0.9
    packet.quote_confidence_assessment.quote_confidence_level = "high"
    warnings = apply_business_guardrails(packet, req)
    assert packet.manual_review.required is True
    assert packet.quote_confidence_assessment.confidence_score <= 0.45
    assert any(w.code == "UNSUPPORTED_FAST_PRECISE_QUOTE" for w in warnings)


def test_slow_response_not_auto_low_engagement(make_request):
    req = make_request(
        trade_processing_factors={
            "material": {"material_availability_status": "supplier_confirmation_required"},
            "behavior": {"explicit_material_supplier_signal": 1.0},
        }
    )
    packet = GLTGAssessmentPacket()
    packet.material_availability_assessment.material_availability_status = (
        "supplier_confirmation_required"
    )
    packet.response_delay_reason_assessment.most_likely_reason = "low_engagement"
    apply_business_guardrails(packet, req)
    assert packet.response_delay_reason_assessment.most_likely_reason != "low_engagement"


def test_deadline_consistency_overrides_low_risk(make_request):
    req = make_request()
    req.order.deadline_days = 20
    packet = _packet(p50_days=18, p80_days=30, p90_days=40, deadline_risk_level="low")
    warnings = apply_business_guardrails(packet, req)
    assert packet.lead_time_risk_assessment.deadline_risk_level != "low"
    assert any(w.code == "DEADLINE_RISK_INCONSISTENT" for w in warnings)


def test_risk_values_clipped(make_request):
    packet = GLTGAssessmentPacket()
    packet.lead_time_risk_assessment.risk_decomposition.material_availability_risk = 5.0
    packet.lead_time_risk_assessment.risk_decomposition.logistics_risk = -2.0
    validate_and_repair(packet, make_request())
    rd = packet.lead_time_risk_assessment.risk_decomposition
    assert rd.material_availability_risk == 1.0
    assert rd.logistics_risk == 0.0
