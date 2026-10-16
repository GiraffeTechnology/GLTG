"""Provided category/history parameters must replace rule priors, not be ignored."""
import pytest

from gltg.behavioral.schemas import GLTGSimulationRequestV2
from gltg.behavioral.simulator import BehavioralLeadTimeSimulator


def evaluate(**factors):
    req = GLTGSimulationRequestV2.model_validate({
        "request_id": "PRD-PARAMETERS", "tenant_id": "tenant-a", "order": {"quantity": 100},
        "trade_processing_factors": factors})
    return BehavioralLeadTimeSimulator().simulate(req)


@pytest.mark.parametrize("material,expected", [
    ({"material_availability_status": "reserved_stock", "lock_confirmation_days": 2.5}, 2.5),
    ({"material_availability_status": "partial_stock", "partial_shortage_procurement_days": .25}, .25),
    ({"material_availability_status": "substitute_material_required", "substitute_material_approval_days": 1.5,
      "material_procurement_days": 2.25}, 3.75),
    ({"material_availability_status": "unknown", "default_category_material_days": 4, "uncertainty_multiplier": 1.25}, 5),
    ({"material_availability_status": "partial_stock", "stock_coverage_ratio": .99,
      "raw_material_lead_time_estimate_days": 2}, .02),
])
def test_material_status_uses_explicit_prd_duration_parameters(material, expected):
    assert evaluate(material=material).components.material_procurement_days == pytest.approx(expected)


def test_clarification_uses_category_base_and_buyer_history_uses_observed_days():
    req = GLTGSimulationRequestV2.model_validate({
        "request_id": "PRD-BUYER", "tenant_id": "tenant-a", "order": {"quantity": 100},
        "behavior_features": {"buyer": {"buyer_decision_delay_score": .5}},
        "trade_processing_factors": {"requirement": {
            "requirement_completeness_score": .5, "base_clarification_days": 8,
            "historical_avg_buyer_decision_days": 12, "requirement_volatility_score": .25,
            "requirement_change_buffer_days": 8, "sample_approval_delay_score": .5,
            "sample_approval_days": 6, "payment_delay_risk": .5, "payment_start_delay_days": 4}}})
    result = BehavioralLeadTimeSimulator().simulate(req)
    assert result.components.requirement_confirmation_days == 4
    assert result.components.buyer_decision_buffer_days == 13  # 6 + 2 + 3 + 2, once.


def test_zero_observed_buyer_durations_do_not_fall_back_to_positive_priors():
    result = evaluate(requirement={"requirement_volatility_score": 1,
        "requirement_change_buffer_days": 0, "sample_approval_delay_score": 1,
        "sample_approval_days": 0, "payment_delay_risk": 1, "payment_start_delay_days": 0})
    assert result.components.buyer_decision_buffer_days == 0


def test_quote_confidence_uses_explicit_evidence_and_accuracy_scores():
    result = evaluate(behavior={"quote_completeness_score": 1, "historical_quote_accuracy_score": 1,
        "source_evidence_score": 1, "detailed_breakdown_signal": 1},
        material={"material_availability_confidence": 1},
        supplier_execution={"execution_control_score": 1})
    # lead-time confidence retains the disclosed .65 prior when absent.
    assert result.risk_decomposition.quote_confidence_penalty == pytest.approx(.052)
