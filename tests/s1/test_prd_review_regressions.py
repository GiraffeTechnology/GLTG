"""PRD review regressions; execute only in an authorized Linux environment."""

import pytest

from gltg.behavioral.schemas import GLTGSimulationRequestV2
from gltg.behavioral.simulator import BehavioralLeadTimeSimulator


def request_with_accuracy(accuracy=None, error_days=None):
    payload = {
        "request_id": "PRD-REVIEW-ACCURACY",
        "tenant_id": "tenant-a",
        "order": {"quantity": 100},
        "trade_processing_factors": {
            "behavior": {"quote_completeness_score": 1},
            "supplier_execution": {"in_house_capability_confidence": 0.8},
        },
    }
    if accuracy is not None:
        payload["trade_processing_factors"]["behavior"]["historical_quote_accuracy_score"] = accuracy
    if error_days is not None:
        payload["historical_baseline"] = {"historical_quoted_vs_actual_error_days": error_days}
    return GLTGSimulationRequestV2.model_validate(payload)


def careful_probability(request):
    inference = BehavioralLeadTimeSimulator()._response_delay_reason_inference(
        request, execution_control=0.5, material_risk=0.3,
    )
    return inference.probabilities["careful_quotation"]


def test_explicit_historical_accuracy_affects_careful_quotation_including_zero():
    assert careful_probability(request_with_accuracy(0)) < careful_probability(request_with_accuracy(1))


def test_observed_quote_error_affects_careful_quotation_when_score_is_absent():
    assert careful_probability(request_with_accuracy(error_days=14)) < careful_probability(
        request_with_accuracy(error_days=0),
    )


def test_explicit_accuracy_is_not_replaced_by_lead_time_confidence():
    request = request_with_accuracy(0)
    request.behavior_features.supplier.lead_time_confidence_score = 0
    before = careful_probability(request)
    request.behavior_features.supplier.lead_time_confidence_score = 1
    assert careful_probability(request) == before


def test_explanation_distinguishes_evidence_derivation_from_missing_input_priors():
    request = request_with_accuracy(error_days=0)
    request.source_observation_ids = ["GDB_SYN_V1_OBS_000001"]
    request.trade_processing_factors.material.material_availability_status = "partial_stock"
    request.trade_processing_factors.material.stock_coverage_ratio = 0.5
    request.trade_processing_factors.material.raw_material_lead_time_estimate_days = 4
    result = BehavioralLeadTimeSimulator().simulate(request)
    sources = result.explanation_json["factor_input_sources"]
    assert sources["historical_quote_accuracy_score"]["kind"] == "derived"
    assert sources["historical_quote_accuracy_score"]["value"] == 1
    assert sources["source_evidence_score"]["kind"] == "derived"
    assert sources["material_procurement_days"]["kind"] == "derived"
    assert sources["material_procurement_days"]["value"] == pytest.approx(2)
    assert "not observed history" not in result.explanation_json["prior_policy"]


def test_explicit_zero_and_absent_history_have_different_provenance():
    explicit = BehavioralLeadTimeSimulator().simulate(request_with_accuracy(0))
    missing = BehavioralLeadTimeSimulator().simulate(request_with_accuracy())
    explicit_source = explicit.explanation_json["factor_input_sources"]["historical_quote_accuracy_score"]
    missing_source = missing.explanation_json["factor_input_sources"]["historical_quote_accuracy_score"]
    assert explicit_source["kind"] == "explicit"
    assert explicit_source["value"] == 0
    assert missing_source["kind"] == "rule_prior"
    assert missing_source["source_fields"] == []


def test_review_formula_change_has_a_distinct_rule_version():
    assert BehavioralLeadTimeSimulator().simulate(request_with_accuracy()).rule_version == "behavior-rules-v0.4.1"
