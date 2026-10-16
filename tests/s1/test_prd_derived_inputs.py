import pytest
from pydantic import ValidationError

from gltg.behavioral.schemas import GLTGSimulationRequestV2, GLTGTradeProcessingFactors
from gltg.behavioral.simulator import BehavioralLeadTimeSimulator


def test_requirement_completeness_uses_category_defined_counts():
    factors = GLTGTradeProcessingFactors.model_validate({"requirement": {
        "completed_required_fields": 7, "total_required_fields": 10}})
    assert factors.requirement.requirement_completeness_score == .7
    with pytest.raises(ValidationError):
        GLTGTradeProcessingFactors.model_validate({"requirement": {
            "completed_required_fields": 11, "total_required_fields": 10}})


@pytest.mark.parametrize("baseline,expected", [
    ({"supplier_historical_response_seconds": 50, "pair_historical_response_seconds": 100}, 4),
    ({"supplier_historical_response_seconds": 0, "pair_historical_response_seconds": 100}, 2),
    ({"category_baseline_response_seconds": 200}, 1),
    ({"tenant_baseline_response_seconds": 400}, .5),
    ({"global_default_response_seconds": 800}, .25),
])
def test_response_ratio_uses_the_explicit_baseline_hierarchy(baseline, expected):
    factors = GLTGTradeProcessingFactors.model_validate({"behavior": {
        "current_case_supplier_response_seconds": 200, **baseline}})
    assert factors.behavior.supplier_response_delay_ratio == expected


def test_zero_response_time_is_valid_and_missing_history_stays_missing():
    factors = GLTGTradeProcessingFactors.model_validate({"behavior": {
        "current_case_supplier_response_seconds": 0, "supplier_historical_response_seconds": 100,
        "current_case_business_hours_response_seconds": 40, "historical_business_hours_response_seconds": 20}})
    assert factors.behavior.supplier_response_delay_ratio == 0
    assert factors.behavior.business_hours_delay_ratio == 2
    missing = GLTGTradeProcessingFactors.model_validate({"behavior": {"current_case_supplier_response_seconds": 100}})
    assert missing.behavior.supplier_response_delay_ratio is None


def test_supplier_production_fact_is_preserved_when_capacity_is_unknown():
    request = GLTGSimulationRequestV2.model_validate({
        "request_id": "CAPACITY-MISSING", "tenant_id": "tenant-a", "order": {"quantity": 100},
        "supplier": {"production_days": 10.5},
        "trade_processing_factors": {"material": {"material_availability_status": "in_stock"}}})
    result = BehavioralLeadTimeSimulator().simulate(request)
    assert result.components.production_days == 10.5


def test_explicit_category_fallback_and_disruption_delay():
    request = GLTGSimulationRequestV2.model_validate({
        "request_id": "CATEGORY-FALLBACK", "tenant_id": "tenant-a", "order": {"quantity": 100},
        "trade_processing_factors": {
            "processing": {"category_default_production_days": 8, "quantity_band_multiplier": 1.5},
            "logistics_trade": {"logistics_disruption_buffer_days": 2.5}}})
    result = BehavioralLeadTimeSimulator().simulate(request)
    assert result.components.production_days == 12
    assert result.components.logistics_disruption_buffer_days == 2.5


@pytest.mark.parametrize("group", ["supplier", "trade"])
def test_nonfinite_input_cannot_create_a_finite_delivery_claim(group):
    payload = {"request_id": "NONFINITE", "tenant_id": "tenant-a", "order": {"quantity": 100}}
    if group == "supplier":
        payload["supplier"] = {"production_days": float("inf")}
    else:
        payload["trade_processing_factors"] = {"behavior": {"current_case_supplier_response_seconds": float("inf")}}
    with pytest.raises(ValidationError):
        GLTGSimulationRequestV2.model_validate(payload)


def test_absolute_target_uses_an_explicit_evaluation_clock():
    req = GLTGSimulationRequestV2.model_validate({
        "request_id": "DATE-CLOCK", "tenant_id": "tenant-a", "order": {
            "quantity": 100, "target_delivery_date": "2026-01-21", "evaluation_date": "2026-01-01"}})
    assert req.order.deadline_days == 20
    assert BehavioralLeadTimeSimulator().simulate(req).risk.deadline_feasible is not None


def test_date_only_without_a_clock_is_not_silently_ignored():
    with pytest.raises(ValidationError, match="evaluation_date"):
        GLTGSimulationRequestV2.model_validate({
            "request_id": "DATE-MISSING-CLOCK", "tenant_id": "tenant-a",
            "order": {"quantity": 100, "target_delivery_date": "2026-01-21"}})
