from __future__ import annotations

from fastapi.testclient import TestClient

from gltg.api.main import create_app


TENANT = "tenant-a"
SECRET = "test-service-secret"


def _trusted_headers() -> dict[str, str]:
    return {
        "X-Service-Auth": SECRET,
        "X-Service-Tenant-ID": TENANT,
        "X-Service-ID": "aivan",
        "X-GLTG-Contract-Version": "gltg.lead-time.v1",
        "X-AIVAN-Correlation-ID": "corr-a",
        "X-Service-Capability": "lead-time.evaluate",
    }


def test_aivan_discovery_reports_the_real_supported_contract(monkeypatch) -> None:
    monkeypatch.setenv("GLTG_INBOUND_SERVICE_AUTH_SECRET", SECRET)
    response = TestClient(create_app()).get(
        "/api/gltg/v1/discovery",
        headers=_trusted_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "gltg.lead-time.v1"
    assert body["capabilities"] == ["lead-time.evaluate"]
    assert body["evaluation_path"] == "/v2/lead-time/simulate"


def test_private_snapshot_request_fails_closed_until_data_api_can_resolve_it(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GLTG_INBOUND_SERVICE_AUTH_SECRET", SECRET)
    response = TestClient(create_app()).post(
        "/v2/lead-time/simulate",
        headers=_trusted_headers(),
        json={
            "private_snapshot_reference": {
                "snapshot_id": "snapshot-a1",
                "tenant_id": TENANT,
                "snapshot_type": "normalized_requirement",
                "contract_version": "snapshot.v1",
                "adapter_identity": "reference-adapter",
                "dataset_identity": "synthetic-private-v1",
                "source_time": "2026-09-01T00:00:00Z",
                "captured_at": "2026-09-01T00:00:01Z",
                "lineage": ["requirement:tenant-a:quote-001"],
                "canonical_fingerprint": "a" * 64,
            }
        },
    )

    assert response.status_code == 503
    assert response.json()["code"] == "PRIVATE_SNAPSHOT_RESOLUTION_UNAVAILABLE"


def test_private_snapshot_tenant_mismatch_fails_before_resolution(monkeypatch) -> None:
    monkeypatch.setenv("GLTG_INBOUND_SERVICE_AUTH_SECRET", SECRET)
    response = TestClient(create_app()).post(
        "/v2/lead-time/simulate",
        headers=_trusted_headers(),
        json={
            "private_snapshot_reference": {
                "snapshot_id": "snapshot-other",
                "tenant_id": "tenant-b",
                "snapshot_type": "normalized_requirement",
                "contract_version": "snapshot.v1",
                "adapter_identity": "reference-adapter",
                "dataset_identity": "synthetic-private-v1",
                "source_time": "2026-09-01T00:00:00Z",
                "captured_at": "2026-09-01T00:00:01Z",
                "lineage": ["requirement:tenant-b:quote-001"],
                "canonical_fingerprint": "b" * 64,
            }
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "TENANT_CONTEXT_MISMATCH"


def test_current_aivan_v2_payload_preserves_consumer_identity(monkeypatch) -> None:
    """The deployed boundary is HTTP; GLTG must retain Aivan's typed context."""

    monkeypatch.setenv("GLTG_INBOUND_SERVICE_AUTH_SECRET", SECRET)
    monkeypatch.setenv("GLTG_EVALUATOR_MODE", "deterministic")
    response = TestClient(create_app()).post(
        "/v2/lead-time/simulate",
        headers={
            "X-Service-Auth": SECRET,
            "X-Service-Tenant-ID": TENANT,
        },
        json={
            "request_id": "EST_current_aivan",
            "tenant_id": TENANT,
            "source_system": "aivan",
            "source_trace_id": "EST_trace_current_aivan",
            "case_context": {
                "assessment_scope": "supplier_candidate",
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
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["assessment_packet"]["case_context"] == {
        "procurement_case_id": None,
        "rfq_id": None,
        "quote_id": None,
        "po_id": None,
        "buyer_id": None,
        "supplier_id": "SUP-verified",
        "assessment_scope": "supplier_candidate",
    }
    assert body["quantiles"]["p50_days"] <= body["quantiles"]["p80_days"]
    assert body["quantiles"]["p80_days"] <= body["quantiles"]["p90_days"]
    assert all(value >= 0 for value in body["quantiles"].values())


def test_unknown_aivan_assessment_scope_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("GLTG_INBOUND_SERVICE_AUTH_SECRET", SECRET)
    response = TestClient(create_app()).post(
        "/v2/lead-time/simulate",
        headers={
            "X-Service-Auth": SECRET,
            "X-Service-Tenant-ID": TENANT,
        },
        json={
            "request_id": "EST_invalid_scope",
            "tenant_id": TENANT,
            "source_system": "aivan",
            "case_context": {"assessment_scope": "untrusted_scope"},
            "order": {"product_type": "shirt", "quantity": 100},
            "supplier": {"supplier_id": "requirement-baseline"},
        },
    )

    assert response.status_code == 422
