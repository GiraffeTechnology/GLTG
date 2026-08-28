"""Stage 3 giraffe-db evidence integration behavior (respx-mocked transport).

These tests pin the GLTG-side contract: auth/tenant propagation, fail-closed
errors, explicit missing-evidence warnings, truthful persistence status, and
secret redaction. The *real HTTP* acceptance run against a live giraffe-db is
`scripts/validate_gltg_giraffe_db_e2e.py` (results in
docs/stage3/STAGE3_FINAL_VALIDATION.md) — these tests are not a substitute
for it.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from gltg.api.main import app
from gltg.integrations.giraffe_db_client import (
    GiraffeDBAuthError,
    GiraffeDBClient,
    GiraffeDBNotFound,
    GiraffeDBUnavailable,
)

client = TestClient(
    app,
    headers={
        "X-Service-Auth": "test-inbound-secret",
        "X-Service-Tenant-ID": "tenant-demo",
    },
)

BASE = "http://giraffe-db.test"
SUPPLIER_ID = "GDB_SYN_V1_SUP_000001"
TENANT = "tenant-demo"

SUPPLIER_RECORD = {
    "supplier_id": SUPPLIER_ID,
    "supplier_name": "PT Sinar Apparel (Bandung)",
    "name_en": "PT Sinar Apparel (Bandung)",
    "tenant_id": TENANT,
    "country": "Indonesia",
    "active": True,
    "is_synthetic": True,
}
EMPTY_SUMMARY = {
    "supplier_id": SUPPLIER_ID,
    "tenant_id": TENANT,
    "observation_count": 0,
    "latest_snapshot": None,
    "response_delay": {"response_delay_ratio": None},
}


def _payload(**overrides) -> dict:
    payload = {
        "request_id": "GDB-1",
        "tenant_id": TENANT,
        "order": {"product_type": "t-shirt", "quantity": 1000, "deadline_days": 150},
        "supplier": {"supplier_id": SUPPLIER_ID, "capacity_per_day": 500},
        "evidence": {"use_giraffe_db": True},
        "source_observation_ids": [],
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def gdb_env(monkeypatch):
    monkeypatch.setenv("GLTG_GIRAFFE_DB_BASE_URL", BASE)
    monkeypatch.setenv("GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET", "s3cret")
    monkeypatch.delenv("GLTG_PERSIST_RUNS", raising=False)


class TestClientErrorMapping:
    def test_timeout_maps_to_db_unavailable(self):
        gdb = GiraffeDBClient(BASE, "s3cret", timeout_seconds=0.1)
        with respx.mock:
            respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}").mock(
                side_effect=httpx.ConnectTimeout("boom")
            )
            with pytest.raises(GiraffeDBUnavailable):
                gdb.get_supplier(SUPPLIER_ID, TENANT)

    def test_401_and_403_map_to_auth_error(self):
        gdb = GiraffeDBClient(BASE, "wrong")
        with respx.mock:
            respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}").mock(
                return_value=httpx.Response(403, json={"detail": {"error": "forbidden"}})
            )
            with pytest.raises(GiraffeDBAuthError):
                gdb.get_supplier(SUPPLIER_ID, TENANT)

    def test_404_maps_to_not_found(self):
        gdb = GiraffeDBClient(BASE, "s3cret")
        with respx.mock:
            respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}").mock(
                return_value=httpx.Response(404, json={"detail": {"error": "not_found"}})
            )
            with pytest.raises(GiraffeDBNotFound):
                gdb.get_supplier(SUPPLIER_ID, TENANT)

    def test_auth_and_tenant_headers_are_sent(self):
        gdb = GiraffeDBClient(BASE, "s3cret")
        with respx.mock:
            route = respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}").mock(
                return_value=httpx.Response(200, json=SUPPLIER_RECORD)
            )
            gdb.get_supplier(SUPPLIER_ID, TENANT)
        request = route.calls[0].request
        assert request.headers["X-Service-Auth"] == "s3cret"
        assert request.headers["X-Service-Tenant-ID"] == TENANT

    def test_secret_is_redacted_in_repr(self):
        gdb = GiraffeDBClient(BASE, "super-secret-value")
        assert "super-secret-value" not in repr(gdb)
        assert "***" in repr(gdb)


class TestSimulationEvidencePath:
    def test_db_unavailable_returns_503_with_code(self, gdb_env):
        with respx.mock:
            respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}").mock(
                side_effect=httpx.ConnectError("down")
            )
            response = client.post("/v2/lead-time/simulate", json=_payload())
        assert response.status_code == 503
        assert response.json()["code"] == "DB_UNAVAILABLE"

    def test_auth_failure_fails_closed_502(self, gdb_env):
        with respx.mock:
            respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}").mock(
                return_value=httpx.Response(401, json={"detail": {"error": "unauthorized"}})
            )
            response = client.post("/v2/lead-time/simulate", json=_payload())
        assert response.status_code == 502
        assert response.json()["code"] == "EVIDENCE_AUTH_FAILED"

    def test_supplier_404_creates_missing_evidence_warning(self, gdb_env):
        with respx.mock:
            respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}").mock(
                return_value=httpx.Response(404, json={"detail": {"error": "not_found"}})
            )
            response = client.post("/v2/lead-time/simulate", json=_payload())
        assert response.status_code == 200
        body = response.json()
        codes = {w["code"] for w in body["warnings"]}
        assert "EVIDENCE_NOT_FOUND" in codes
        assert body["risk"]["manual_review_required"] is True
        assert body["explanation_json"]["evidence"]["status"] == "supplier_not_found"

    def test_malformed_supplier_record_fails_validation(self, gdb_env):
        with respx.mock:
            respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}").mock(
                return_value=httpx.Response(200, json={"unexpected": "shape"})
            )
            response = client.post("/v2/lead-time/simulate", json=_payload())
        assert response.status_code == 422
        assert "EVIDENCE_MALFORMED" in response.json()["error"]

    def test_missing_behavior_evidence_lowers_confidence_with_warning(self, gdb_env):
        with respx.mock:
            respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}").mock(
                return_value=httpx.Response(200, json=SUPPLIER_RECORD)
            )
            respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}/behavior-summary").mock(
                return_value=httpx.Response(200, json=EMPTY_SUMMARY)
            )
            with_evidence = client.post("/v2/lead-time/simulate", json=_payload()).json()
        no_evidence_payload = _payload(evidence={"use_giraffe_db": False})
        without_evidence = client.post("/v2/lead-time/simulate", json=no_evidence_payload).json()
        codes = {w["code"] for w in with_evidence["warnings"]}
        assert "MISSING_BEHAVIOR_EVIDENCE" in codes
        assert "SYNTHETIC_EVIDENCE" in codes
        assert (
            with_evidence["risk"]["confidence_score"]
            < without_evidence["risk"]["confidence_score"]
        )
        # No invented behavior: quantiles unchanged vs. the no-evidence run.
        assert with_evidence["quantiles"] == without_evidence["quantiles"]

    def test_snapshot_features_feed_simulation_and_lineage(self, gdb_env):
        summary = {
            "supplier_id": SUPPLIER_ID,
            "tenant_id": TENANT,
            "observation_count": 12,
            "latest_snapshot": {
                "snapshot_id": "GDB_SYN_V1_SUPFEAT_000001",
                "feature_json": {"response_delay_ratio": 3.5},
            },
            "response_delay": {"response_delay_ratio": 3.5},
        }
        with respx.mock:
            respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}").mock(
                return_value=httpx.Response(200, json=SUPPLIER_RECORD)
            )
            respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}/behavior-summary").mock(
                return_value=httpx.Response(200, json=summary)
            )
            body = client.post("/v2/lead-time/simulate", json=_payload()).json()
        assert "GDB_SYN_V1_SUPFEAT_000001" in body["source_observation_ids"]
        assert any(
            w["code"] == "SUPPLIER_RESPONSE_DELAY_ANOMALY" for w in body["warnings"]
        )

    def test_no_silent_mock_fallback_when_unconfigured(self, monkeypatch):
        monkeypatch.delenv("GLTG_GIRAFFE_DB_BASE_URL", raising=False)
        response = client.post("/v2/lead-time/simulate", json=_payload())
        assert response.status_code == 503
        assert response.json()["code"] == "DB_UNAVAILABLE"


class TestPersistenceTruthfulness:
    def test_disabled_persistence_reports_status(self, gdb_env):
        payload = _payload(evidence={"use_giraffe_db": False})
        body = client.post("/v2/lead-time/simulate", json=payload).json()
        assert body["persistence"]["status"] == "skipped"
        assert body["persistence"]["persisted_to_giraffe_db"] is False

    def test_unconfigured_persistence_reports_unavailable(self, monkeypatch):
        monkeypatch.delenv("GLTG_GIRAFFE_DB_BASE_URL", raising=False)
        monkeypatch.delenv("GLTG_PERSIST_RUNS", raising=False)
        payload = _payload(evidence={"use_giraffe_db": False})
        body = client.post("/v2/lead-time/simulate", json=payload).json()
        assert body["persistence"]["status"] == "unavailable"

    def test_persist_success_records_giraffe_db_run_id(self, gdb_env, monkeypatch):
        monkeypatch.setenv("GLTG_PERSIST_RUNS", "true")
        payload = _payload(evidence={"use_giraffe_db": False})
        with respx.mock:
            route = respx.post(f"{BASE}/api/data/gltg-simulation-runs").mock(
                return_value=httpx.Response(
                    200, json={"gltg_run_id": "GDB_SYN_V1_GLTG_000001", "tenant_id": TENANT}
                )
            )
            body = client.post("/v2/lead-time/simulate", json=payload).json()
        assert body["persistence"]["status"] == "persisted"
        assert body["persistence"]["giraffe_db_run_id"] == "GDB_SYN_V1_GLTG_000001"
        request = route.calls[0].request
        assert request.headers["X-Service-Tenant-ID"] == TENANT
        assert request.headers["X-Service-Auth"] == "s3cret"

    def test_persist_failure_is_truthful_not_success(self, gdb_env, monkeypatch):
        monkeypatch.setenv("GLTG_PERSIST_RUNS", "true")
        payload = _payload(evidence={"use_giraffe_db": False})
        with respx.mock:
            respx.post(f"{BASE}/api/data/gltg-simulation-runs").mock(
                return_value=httpx.Response(500, json={"error": "boom"})
            )
            body = client.post("/v2/lead-time/simulate", json=payload).json()
        assert body["persistence"]["status"] == "failed"
        assert body["persistence"]["persisted_to_giraffe_db"] is False
        assert any(w["code"] == "PERSISTENCE_FAILED" for w in body["warnings"])

    def test_duplicate_request_same_internal_run_id(self, gdb_env):
        payload = _payload(evidence={"use_giraffe_db": False})
        first = client.post("/v2/lead-time/simulate", json=payload).json()
        second = client.post("/v2/lead-time/simulate", json=payload).json()
        assert first["gltg_run_id"] == second["gltg_run_id"]
