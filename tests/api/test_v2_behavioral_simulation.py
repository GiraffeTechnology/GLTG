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
