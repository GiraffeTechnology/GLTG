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
