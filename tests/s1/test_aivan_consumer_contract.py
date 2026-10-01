from __future__ import annotations

from fastapi.testclient import TestClient

from gltg.api.main import create_app


TENANT = "tenant-a"
SECRET = "test-service-secret"


def _payload(scope: str) -> dict:
    return {
        "request_id": "EST_current_aivan",
        "tenant_id": TENANT,
        "source_system": "aivan",
        "source_trace_id": "EST_trace_current_aivan",
        "case_context": {
            "assessment_scope": scope,
            "supplier_id": "SUP-verified",
        },
        "order": {
            "product_type": "industrial fastener",
            "quantity": 750,
            "quantity_unit": "kg",
            "destination": "Osaka",
            "deadline_days": 28,
        },
        "supplier": {
            "supplier_id": "SUP-verified",
            "capacity_per_day": 125,
            "confidence": 0.7,
        },
        "constraints": {"lead_time_confidence": "P80"},
    }


def _post(monkeypatch, scope: str):
    monkeypatch.setenv("GLTG_INBOUND_SERVICE_AUTH_SECRET", SECRET)
    monkeypatch.setenv("GLTG_EVALUATOR_MODE", "deterministic")
    return TestClient(create_app()).post(
        "/v2/lead-time/simulate",
        headers={
            "X-Service-Auth": SECRET,
            "X-Service-Tenant-ID": TENANT,
        },
        json=_payload(scope),
    )


def test_current_aivan_http_payload_preserves_typed_consumer_context(monkeypatch) -> None:
    response = _post(monkeypatch, "supplier_candidate")

    assert response.status_code == 200
    body = response.json()
    assert body["assessment_packet"]["case_context"]["assessment_scope"] == "supplier_candidate"
    assert body["assessment_packet"]["case_context"]["supplier_id"] == "SUP-verified"
    quantiles = body["quantiles"]
    assert 0 <= quantiles["p50_days"] <= quantiles["p80_days"] <= quantiles["p90_days"]


def test_unknown_aivan_assessment_scope_is_rejected(monkeypatch) -> None:
    response = _post(monkeypatch, "untrusted_scope")

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
