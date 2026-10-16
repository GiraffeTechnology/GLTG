"""Executable PRD sections 6-7 regression vectors."""

import pytest

from gltg.behavioral.schemas import GLTGSimulationRequestV2
from gltg.behavioral.simulator import BehavioralLeadTimeSimulator
from gltg.errors import GLTGError


def request(**groups):
    return GLTGSimulationRequestV2.model_validate({
        "request_id": "PRD-FACTORS", "tenant_id": "tenant-a",
        "order": {"quantity": 100, "deadline_days": 1000},
        "supplier": {"capacity_per_day": 100},
        "trade_processing_factors": {
            "requirement": {"requirement_completeness_score": 1},
            "material": {"material_availability_status": "in_stock",
                         "material_availability_confidence": 1},
            **groups,
        },
    })


def test_capacity_has_no_invented_availability_floor():
    req = request(supplier_execution={"nominal_daily_capacity": 100,
                                     "capacity_utilization_ratio": .99},
                  processing={"expected_yield_rate": 1})
    engine = BehavioralLeadTimeSimulator()
    assert engine._effective_daily_capacity(req, 1) == pytest.approx(1)
    assert engine.simulate(req).components.production_days == 100


@pytest.mark.parametrize("execution,processing", [
    ({"effective_daily_capacity": 0}, {}),
    ({"nominal_daily_capacity": 100, "capacity_utilization_ratio": 1}, {}),
    ({"nominal_daily_capacity": 100}, {"expected_yield_rate": 0}),
])
def test_zero_capacity_cannot_produce_a_finite_delivery_promise(execution, processing):
    with pytest.raises(GLTGError, match="CAPACITY_UNAVAILABLE"):
        BehavioralLeadTimeSimulator().simulate(request(
            supplier_execution=execution, processing=processing))


def test_buyer_decision_delay_counted_once():
    req = request(requirement={"requirement_completeness_score": 1,
                               "requirement_volatility_score": .5})
    req.behavior_features.buyer.buyer_decision_delay_score = .5
    result = BehavioralLeadTimeSimulator().simulate(req)
    assert result.components.buyer_decision_buffer_days == 4.5
    assert result.quantiles.p50_days == pytest.approx(
        BehavioralLeadTimeSimulator._trade_processing_base_days(result.components)
        + result.components.supplier_response_buffer_days)


def test_response_speed_is_not_direct_engagement_risk_with_material_reason():
    req = request(behavior={"supplier_response_delay_ratio": 5,
                           "business_hours_delay_ratio": 5,
                           "most_likely_response_delay_reason": "raw_material_supplier_confirmation",
                           "low_engagement_probability": 0})
    result = BehavioralLeadTimeSimulator().simulate(req)
    assert result.components.supplier_response_buffer_days == 0
    assert not any(w.code in {"SUPPLIER_RESPONSE_DELAY_ANOMALY", "BUSINESS_HOURS_DELAY"}
                   for w in result.warnings)
    assert result.risk_decomposition.engagement_risk == 0


def test_stock_ratio_is_derived_from_observed_quantities():
    req = request(material={"required_material_qty": 100,
                            "available_material_qty": 25,
                            "raw_material_lead_time_estimate_days": 8})
    assert req.trade_processing_factors.material.stock_coverage_ratio == .25
    assert req.trade_processing_factors.material.material_availability_status == "partial_stock"
    assert BehavioralLeadTimeSimulator().simulate(req).components.material_procurement_days == 6


def test_confirmed_booking_does_not_add_unconfirmed_freight_wait():
    result = BehavioralLeadTimeSimulator().simulate(request(
        logistics_trade={"departure_frequency_days": 7, "freight_space_risk": .8,
                         "booking_confirmed": True}))
    assert result.components.departure_wait_days == 3.5


def test_customs_formula_and_manual_review_threshold():
    result = BehavioralLeadTimeSimulator().simulate(request(
        logistics_trade={"customs_inspection_probability": .5,
                         "expected_customs_delay_days": 4,
                         "trade_compliance_risk": .7,
                         "manual_review_delay_days": 3}))
    assert result.components.customs_risk_buffer_days == 4.1
    assert result.risk.manual_review_required


def test_rework_probability_formula_without_supplied_probability():
    result = BehavioralLeadTimeSimulator().simulate(request(processing={
        "base_category_defect_rate": .05, "new_supplier_flag": True,
        "material_substitution_flag": True, "rushed_order_flag": True,
        "historical_quality_score": .8, "rework_days_if_triggered": 10}))
    assert result.components.expected_rework_days == 2.2


def test_explanation_separates_median_and_tail_drivers():
    result = BehavioralLeadTimeSimulator().simulate(request())
    explanation = result.explanation_json
    assert explanation["median_drivers"]
    assert explanation["tail_drivers"]
    assert explanation["material_availability_status"] == "in_stock"
    assert explanation["source_observation_ids"] == []
