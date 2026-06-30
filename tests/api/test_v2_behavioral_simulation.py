"""Tests for the GLTG v2 behavioral/statistical simulation API."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from gltg.api.main import app
from gltg.behavioral.schemas import GLTGSimulationRequestV2, GLTGSimulationResponseV2

client = TestClient(app)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _trade_payload(name: str, factors: dict, deadline_days: int = 90) -> dict:
    payload = _fixture("gltg_v2_simulation_request.json")
    payload["request_id"] = name
    payload["order"]["deadline_days"] = deadline_days
    payload["trade_processing_factors"] = factors
    return payload


def _simulate_trade(name: str, factors: dict, deadline_days: int = 90) -> dict:
    response = client.post("/v2/lead-time/simulate", json=_trade_payload(name, factors, deadline_days))
    assert response.status_code == 200
    return response.json()


def test_v2_contract_fixtures_validate():
    req = GLTGSimulationRequestV2(**_fixture("gltg_v2_simulation_request.json"))
    assert req.case_context.buyer_id == "GDB_SYN_V1_BUYER_000001"
    assert req.behavior_features.supplier.response_delay_ratio == 3.0

    response = GLTGSimulationResponseV2(**_fixture("gltg_v2_simulation_response.json"))
    assert response.model_version == "gltg-hybrid-v0.1.0"
    assert response.explanation_json["composer"] == "pseudo_lognormal"


def test_v2_simulate_success_maps_behavior_outputs():
    payload = _fixture("gltg_v2_simulation_request.json")
    res = client.post("/v2/lead-time/simulate", json=payload)
    assert res.status_code == 200
    body = res.json()

    assert body["ok"] is True
    assert body["model_version"] == "gltg-hybrid-v0.1.0"
    assert body["rule_version"] == "behavior-rules-v0.1.0"
    assert body["quantiles"]["p50_days"] <= body["quantiles"]["p80_days"] <= body["quantiles"]["p90_days"]
    assert body["components"]["supplier_response_buffer_days"] >= 3
    assert body["components"]["supplier_uncertainty_buffer_days"] >= 2
    assert body["components"]["buyer_decision_buffer_days"] >= 4
    assert body["explanation_json"]["composer"] == "pseudo_lognormal"
    assert body["explanation_json"]["composition_parameters"]["delta_sigma"] > 0
    assert body["risk"]["fallback_supplier_required"] is True
    assert body["risk"]["manual_review_required"] is True
    assert body["explanation_json"]["source_observation_ids"] == payload["source_observation_ids"]
    assert any(w["code"] == "SUPPLIER_RESPONSE_DELAY_ANOMALY" for w in body["warnings"])


def test_v2_low_risk_behavior_has_no_manual_review_or_fallback():
    payload = _fixture("gltg_v2_simulation_request.json")
    payload["order"]["deadline_days"] = 90
    payload["behavior_features"]["supplier"].update({
        "response_delay_ratio": 1.0,
        "business_hours_delay_ratio": 1.0,
        "quote_completeness_score": 0.95,
        "lead_time_revision_count": 0,
        "upstream_confirmation_signal": 0.0,
    })
    payload["behavior_features"]["buyer"].update({
        "requirement_change_count": 0,
        "buyer_decision_delay_score": 0.1,
    })
    body = client.post("/v2/lead-time/simulate", json=payload).json()
    assert body["risk"]["deadline_risk_level"] == "low"
    assert body["risk"]["fallback_supplier_required"] is False
    assert body["risk"]["manual_review_required"] is False
    assert body["components"]["supplier_response_buffer_days"] == 0


def test_v2_without_baseline_distribution_uses_deterministic_fallback_composer():
    payload = _fixture("gltg_v2_simulation_request.json")
    payload["historical_baseline"] = {}
    body = client.post("/v2/lead-time/simulate", json=payload).json()
    assert body["explanation_json"]["composer"] == "deterministic_fallback"
    assert body["explanation_json"]["baseline_source"] == "gltg_requirement_baseline"
    assert body["quantiles"]["p50_days"] <= body["quantiles"]["p80_days"] <= body["quantiles"]["p90_days"]


def test_v2_missing_source_observations_are_warned_not_invented():
    payload = _fixture("gltg_v2_simulation_request.json")
    payload["source_observation_ids"] = []
    body = client.post("/v2/lead-time/simulate", json=payload).json()
    assert body["explanation_json"]["source_observation_ids"] == []
    assert any(w["code"] == "MISSING_SOURCE_OBSERVATIONS" for w in body["warnings"])


def test_v2_paths_enumerate_ranks_multiple_simulations():
    payload = _fixture("gltg_v2_simulation_request.json")
    slow = {**payload, "request_id": "REQ_slow"}
    fast = json.loads(json.dumps(payload))
    fast["request_id"] = "REQ_fast"
    fast["supplier"]["supplier_id"] = "FAST"
    fast["historical_baseline"]["baseline_p50_days"] = 20
    fast["historical_baseline"]["baseline_p80_days"] = 25
    fast["historical_baseline"]["baseline_p90_days"] = 30

    body = client.post("/v2/paths/enumerate", json={"simulations": [slow, fast]}).json()
    assert [p["rank"] for p in body["paths"]] == [1, 2]
    assert body["paths"][0]["supplier_id"] == "FAST"


def test_v2_reforecast_echoes_events_and_returns_simulation():
    payload = _fixture("gltg_v2_simulation_request.json")
    payload["events"] = [{"event_type": "supplier_delay", "delay_days": 3}]
    body = client.post("/v2/reforecast", json=payload).json()
    assert body["ok"] is True
    assert body["applied_events"] == payload["events"]


def test_trade_factor_fast_response_material_in_stock_has_low_material_risk():
    body = _simulate_trade(
        "TRADE_A_in_stock",
        {
            "requirement": {"requirement_completeness_score": 0.95},
            "supplier_execution": {
                "supplier_execution_mode": "in_house_manufacturer",
                "in_house_capability_confidence": 0.90,
                "capacity_utilization_ratio": 0.40,
            },
            "material": {
                "material_availability_status": "in_stock",
                "stock_coverage_ratio": 1.0,
                "material_availability_confidence": 0.95,
            },
            "behavior": {
                "supplier_response_delay_ratio": 1.0,
                "quote_completeness_score": 0.95,
                "supplier_response_fast": True,
                "detailed_breakdown_signal": 0.8,
            },
            "logistics_trade": {
                "route_baseline_days": 18,
                "departure_frequency_days": 7,
                "export_doc_readiness_score": 0.95,
            },
        },
    )

    assert body["explanation_json"]["composer"] == "trade_processing_factor_spread"
    assert body["risk_decomposition"]["material_availability_risk"] < 0.10
    assert body["explanation_json"]["trade_processing_factor_scores"]["quote_confidence_score"] > 0.80
    assert body["risk"]["fallback_supplier_required"] is False
    assert body["components"]["material_procurement_days"] == 0


def test_trade_factor_slow_response_material_confirmation_not_low_engagement():
    body = _simulate_trade(
        "TRADE_B_material_confirmation",
        {
            "requirement": {"requirement_completeness_score": 0.85},
            "supplier_execution": {
                "supplier_execution_mode": "in_house_manufacturer",
                "in_house_capability_confidence": 0.85,
                "capacity_utilization_ratio": 0.55,
            },
            "material": {
                "material_availability_status": "supplier_confirmation_required",
                "stock_coverage_ratio": 0.0,
                "material_availability_confidence": 0.35,
                "raw_material_supplier_confirmation_probability": 0.90,
                "raw_material_lead_time_estimate_days": 5,
                "raw_material_lead_time_uncertainty_score": 0.80,
            },
            "behavior": {
                "supplier_response_delay_ratio": 3.0,
                "business_hours_delay_ratio": 2.5,
                "quote_completeness_score": 0.75,
                "explicit_material_supplier_signal": 1.0,
                "material_keywords": 0.8,
                "explicit_checking_signal": 0.8,
                "no_clear_reason_signal": 0.0,
            },
            "logistics_trade": {"route_baseline_days": 18, "departure_frequency_days": 7},
        },
    )

    reason = body["response_delay_reason_inference"]
    assert reason["most_likely_reason"] == "raw_material_supplier_confirmation"
    assert reason["probabilities"]["raw_material_supplier_confirmation"] > reason["probabilities"]["low_engagement"]
    assert body["risk_decomposition"]["material_availability_risk"] > 0.50
    assert body["explanation_json"]["trade_processing_factor_scores"]["execution_control_score"] > 0.60
    assert body["components"]["material_procurement_days"] == 5
    assert "raw material supplier confirmation" in body["explanation_json"]["summary"]


def test_trade_factor_fast_unsupported_precise_quote_reduces_confidence():
    body = _simulate_trade(
        "TRADE_C_unsupported_fast_quote",
        {
            "requirement": {"requirement_completeness_score": 0.80, "deadline_strictness_score": 0.90},
            "supplier_execution": {
                "supplier_execution_mode": "in_house_manufacturer",
                "in_house_capability_confidence": 0.50,
            },
            "material": {
                "material_availability_status": "unknown",
                "material_availability_confidence": 0.0,
            },
            "behavior": {
                "supplier_response_delay_ratio": 0.5,
                "quote_completeness_score": 0.65,
                "supplier_response_fast": True,
                "unsupported_precise_leadtime_signal": True,
            },
            "logistics_trade": {"route_baseline_days": 18},
        },
        deadline_days=45,
    )

    assert body["explanation_json"]["trade_processing_factor_scores"]["quote_confidence_score"] < 0.50
    assert body["risk"]["manual_review_required"] is True
    assert any(w["code"] == "UNSUPPORTED_FAST_PRECISE_QUOTE" for w in body["warnings"])


def test_trade_factor_trader_material_pending_widens_tail_and_requires_fallback():
    body = _simulate_trade(
        "TRADE_D_trader_material_pending",
        {
            "requirement": {"requirement_completeness_score": 0.75, "deadline_strictness_score": 0.90},
            "supplier_execution": {
                "supplier_execution_mode": "trader",
                "in_house_capability_confidence": 0.15,
                "upstream_dependency_probability": 0.90,
                "capacity_utilization_ratio": 0.75,
            },
            "material": {
                "material_availability_status": "supplier_confirmation_required",
                "material_availability_confidence": 0.25,
                "raw_material_supplier_confirmation_probability": 0.90,
                "raw_material_lead_time_estimate_days": 7,
                "raw_material_lead_time_uncertainty_score": 0.80,
            },
            "processing": {"external_subprocess_dependency_score": 0.60},
            "behavior": {
                "supplier_response_delay_ratio": 2.4,
                "quote_completeness_score": 0.55,
                "explicit_material_supplier_signal": 0.8,
            },
            "logistics_trade": {"route_baseline_days": 18, "departure_frequency_days": 7},
        },
        deadline_days=45,
    )

    assert body["risk_decomposition"]["upstream_dependency_risk"] >= 0.90
    assert body["explanation_json"]["trade_processing_factor_scores"]["execution_control_score"] < 0.40
    assert body["risk_decomposition"]["lead_time_uncertainty_risk"] > 0.40
    assert body["risk"]["fallback_supplier_required"] is True
    assert body["quantiles"]["p90_days"] - body["quantiles"]["p50_days"] > 12


def test_trade_factor_formula_outputs_are_deterministic_and_monotonic():
    body = _simulate_trade(
        "TRADE_formula_check",
        {
            "requirement": {
                "requirement_completeness_score": 0.80,
                "requirement_volatility_score": 0.25,
                "quality_requirement_level_score": 0.50,
                "packaging_complexity_score": 0.25,
            },
            "supplier_execution": {
                "supplier_execution_mode": "in_house_manufacturer",
                "in_house_capability_confidence": 0.82,
                "capacity_utilization_ratio": 0.72,
                "nominal_daily_capacity": 500,
            },
            "material": {
                "material_availability_status": "supplier_confirmation_required",
                "material_availability_confidence": 0.35,
                "raw_material_supplier_confirmation_probability": 0.75,
                "raw_material_lead_time_estimate_days": 5,
                "raw_material_lead_time_uncertainty_score": 0.68,
                "substitute_material_probability": 0.12,
            },
            "processing": {
                "customization_level_score": 0.40,
                "sample_required": True,
                "sample_days": 3,
                "external_subprocess_dependency_score": 0.20,
                "expected_yield_rate": 0.95,
                "rework_probability": 0.08,
            },
            "logistics_trade": {
                "route_baseline_days": 18,
                "departure_frequency_days": 7,
                "freight_space_risk": 0.20,
                "customs_inspection_probability": 0.10,
                "trade_compliance_risk": 0.05,
                "calendar_disruption_score": 0.20,
                "logistics_disruption_score": 0.15,
            },
            "behavior": {
                "supplier_response_delay_ratio": 3.0,
                "business_hours_delay_ratio": 2.5,
                "quote_completeness_score": 0.65,
                "explicit_material_supplier_signal": 1.0,
            },
        },
    )

    assert body["components"]["capacity_queue_days"] > 0
    assert body["components"]["departure_wait_days"] == 4.9
    assert body["risk_decomposition"]["capacity_risk"] == 0.1
    assert body["risk_decomposition"]["lead_time_uncertainty_risk"] > 0
    assert body["quantiles"]["p50_days"] <= body["quantiles"]["p80_days"] <= body["quantiles"]["p90_days"]
