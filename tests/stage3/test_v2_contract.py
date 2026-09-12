"""Stage 3 v2 API contract tests (real app object, default deterministic mode)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gltg.api.main import app

client = TestClient(
    app,
    headers={
        "X-Service-Auth": "test-inbound-secret",
        "X-Service-Tenant-ID": "tenant-a",
    },
)

PAYLOAD = {
    "request_id": "CONTRACT-1",
    "tenant_id": "tenant-a",
    "order": {"product_type": "t-shirt", "quantity": 5000, "deadline_days": 120},
    "supplier": {
        "supplier_id": "GDB_SYN_V1_SUP_000001",
        "capacity_per_day": 500,
        "material_ready_days": 7,
        "production_days": 12,
        "qc_days": 3,
        "logistics_days": 18,
        "confidence": 0.75,
    },
    "source_observation_ids": ["GDB_SYN_V1_OBS_000001"],
}

REQUIRED_TOP_LEVEL = [
    "gltg_run_id",
    "model_version",
    "rule_version",
    "calibration_version",
    "quantiles",
    "components",
    "risk",
    "explanation_json",
    "warnings",
    "persistence",
    "source_observation_ids",
]

REQUIRED_RISK = [
    "deadline_risk_level",
    "confidence_score",
    "fallback_supplier_required",
    "manual_review_required",
    "deadline_feasible",
    "selected_confidence_days",
]


def test_v2_simulate_returns_required_contract():
    response = client.post("/v2/lead-time/simulate", json=PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    for field in REQUIRED_TOP_LEVEL:
        assert field in body, f"missing {field}"
    for field in ("p50_days", "p80_days", "p90_days"):
        assert isinstance(body["quantiles"][field], (int, float))
    for field in REQUIRED_RISK:
        assert field in body["risk"], f"missing risk.{field}"
    assert body["evaluation_mode"] == "deterministic"
    assert body["model_provider"] == "deterministic_rules"
    assert body["persistence"]["status"] in {"unavailable", "skipped", "persisted", "failed"}
    assert body["source_observation_ids"] == PAYLOAD["source_observation_ids"]


def test_v2_default_mode_is_deterministic_no_llm(monkeypatch):
    """Out of the box (no GLTG_* env), v2 must not attempt any LLM call."""
    for var in (
        "GLTG_EVALUATOR_MODE",
        "GLTG_LLM_PROVIDER",
        "GLTG_LLM_BASE_URL",
        "GLTG_LLM_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)

    import sys

    orchestrator_module = sys.modules["gltg.evaluator.orchestrator"]

    def _fail_provider(*args, **kwargs):  # pragma: no cover - should never run
        raise AssertionError("LLM provider must not be constructed in default mode")

    monkeypatch.setattr(orchestrator_module, "get_provider", _fail_provider)
    body = client.post("/v2/lead-time/simulate", json=PAYLOAD).json()
    assert body["evaluation_mode"] == "deterministic"


def test_v2_every_nonzero_adjustment_is_explained():
    payload = {
        **PAYLOAD,
        "request_id": "CONTRACT-EXPL",
        "behavior_features": {
            "supplier": {"response_delay_ratio": 2.5, "quote_completeness_score": 0.6},
        },
    }
    body = client.post("/v2/lead-time/simulate", json=payload).json()
    adjustments = body["explanation_json"]["adjustments"]
    features = {adj["feature"] for adj in adjustments}
    assert "supplier_response_delay_ratio" in features
    assert "quote_completeness_score" in features
    for adj in adjustments:
        assert adj["reason"]
        assert adj["adjustment"]


def test_v2_malformed_request_is_422_with_error_envelope():
    response = client.post("/v2/lead-time/simulate", json={"request_id": "X"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"


def test_v2_negative_quantity_rejected_or_bounded():
    payload = {**PAYLOAD, "order": {"product_type": "t-shirt", "quantity": -5}}
    response = client.post("/v2/lead-time/simulate", json=payload)
    if response.status_code == 200:
        quantiles = response.json()["quantiles"]
        assert quantiles["p50_days"] >= 0
    else:
        assert response.status_code == 422


def test_health_ready_version_endpoints():
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/ready").json()
    assert "ready" in ready and "evaluator_mode" in ready and "giraffe_db" in ready
    assert ready["giraffe_db"] in {"not_configured", "ok", "unreachable"}
    version = client.get("/version").json()
    assert version["service"] == "gltg"
