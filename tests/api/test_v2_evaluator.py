"""GLTG v2 LLM-assisted evaluator API tests with the mock provider (§18.4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gltg.api.main import app

client = TestClient(app)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(autouse=True)
def _mock_llm_env(monkeypatch):
    monkeypatch.setenv("GLTG_EVALUATOR_MODE", "llm")
    monkeypatch.setenv("GLTG_LLM_PROVIDER", "mock")
    monkeypatch.setenv("GLTG_LLM_MODEL", "qwen3.5")
    monkeypatch.delenv("GLTG_MOCK_SCENARIO", raising=False)


def _request(**overrides) -> dict:
    data = json.loads((FIXTURES / "gltg_v2_simulation_request.json").read_text())
    data.update(overrides)
    return data


def test_simulate_returns_provider_metadata_and_packet():
    res = client.post("/v2/lead-time/simulate", json=_request())
    assert res.status_code == 200
    body = res.json()

    assert body["assessment_schema_version"] == "gltg-assessment-v1"
    assert body["model_provider"] == "mock"
    assert body["model_name"] == "qwen3.5"
    assert body["evaluation_mode"] == "llm"

    assert "quantiles" in body
    q = body["quantiles"]
    assert q["p50_days"] <= q["p80_days"] <= q["p90_days"]

    packet = body["assessment_packet"]
    assert packet["assessment_schema_version"] == "gltg-assessment-v1"
    assert "lead_time_risk_assessment" in packet

    assert body["explanation_json"]["evidence_refs"]
    assert body["explanation_json"]["follow_up_questions"]


def test_simulate_unknown_material_produces_weak_evidence_warnings():
    body = client.post(
        "/v2/lead-time/simulate",
        json=_request(
            trade_processing_factors={
                "material": {"material_availability_status": "unknown"},
                "behavior": {"unsupported_precise_leadtime_signal": True},
            },
            source_observation_ids=[],
        ),
    ).json()
    codes = {w["code"] for w in body["warnings"]}
    assert "UNSUPPORTED_FAST_PRECISE_QUOTE" in codes
    assert body["manual_review_required"] is True


def test_paths_enumerate_ranks_with_evaluator():
    slow = _request(request_id="REQ_slow")
    fast = _request(request_id="REQ_fast")
    fast["supplier"]["supplier_id"] = "FAST"
    fast["historical_baseline"]["baseline_p50_days"] = 12
    fast["historical_baseline"]["baseline_p80_days"] = 14
    fast["historical_baseline"]["baseline_p90_days"] = 16
    body = client.post("/v2/paths/enumerate", json={"simulations": [slow, fast]}).json()
    assert [p["rank"] for p in body["paths"]] == [1, 2]
    assert body["paths"][0]["supplier_id"] == "FAST"


def test_reforecast_echoes_events():
    payload = _request()
    payload["events"] = [{"event_type": "supplier_delay", "delay_days": 3}]
    body = client.post("/v2/reforecast", json=payload).json()
    assert body["ok"] is True
    assert body["applied_events"] == payload["events"]
    assert body["evaluation_mode"] == "llm"
