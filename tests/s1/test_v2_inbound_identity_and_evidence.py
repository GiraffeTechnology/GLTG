from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from gltg.api.main import app
from gltg.api import routes
from gltg.behavioral.schemas import GLTGSimulationRequestV2
from gltg.services import v2_pipeline


SECRET = "test-inbound-secret"
TENANT = "tenant-a"
HEADERS = {
    "X-Service-Auth": SECRET,
    "X-Service-Tenant-ID": TENANT,
}
EXPLICIT = "X-GLTG-Test-Explicit-Identity"


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "request_id": "SECURITY-BOUNDARY-1",
        "tenant_id": TENANT,
        "order": {"product_type": "apparel", "quantity": 100},
        "supplier": {"supplier_id": "SUP-1"},
        "source_observation_ids": [],
        "evidence": {"use_giraffe_db": False},
    }
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def _configured_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLTG_INBOUND_SERVICE_AUTH_SECRET", SECRET)
    monkeypatch.delenv("GLTG_PERSIST_RUNS", raising=False)
    monkeypatch.delenv("GLTG_GIRAFFE_DB_BASE_URL", raising=False)
    monkeypatch.delenv("GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET", raising=False)


@pytest.mark.parametrize(
    ("headers", "status", "code"),
    [
        ({"X-Service-Tenant-ID": TENANT}, 401, "CALLER_AUTH_REQUIRED"),
        ({"X-Service-Auth": SECRET}, 401, "TENANT_CONTEXT_REQUIRED"),
        ({"X-Service-Auth": SECRET, "X-Service-Tenant-ID": "   "}, 401, "TENANT_CONTEXT_REQUIRED"),
        ({"X-Service-Auth": "wrong", "X-Service-Tenant-ID": TENANT}, 401, "CALLER_AUTH_INVALID"),
    ],
)
def test_missing_blank_or_invalid_identity_fails_closed(
    headers: dict[str, str], status: int, code: str
) -> None:
    response = TestClient(app).post(
        "/v2/lead-time/simulate",
        json=_payload(),
        headers={**headers, EXPLICIT: "1"},
    )
    assert response.status_code == status
    assert response.json() == {"error": code, "code": code}


def test_body_tenant_is_required() -> None:
    payload = _payload()
    payload.pop("tenant_id")
    response = TestClient(app).post(
        "/v2/lead-time/simulate", json=payload, headers=HEADERS
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_header_body_tenant_mismatch_rejects_reference_before_calculation() -> None:
    response = TestClient(app).post(
        "/v2/lead-time/simulate",
        json=_payload(source_observation_ids=["foreign-observation"]),
        headers={**HEADERS, "X-Service-Tenant-ID": "tenant-b"},
    )
    assert response.status_code == 403
    assert response.json() == {
        "error": "TENANT_CONTEXT_MISMATCH",
        "code": "TENANT_CONTEXT_MISMATCH",
    }


def test_openapi_marks_identity_headers_required() -> None:
    operation = app.openapi()["paths"]["/v2/lead-time/simulate"]["post"]
    headers = {item["name"]: item for item in operation["parameters"]}
    assert headers["X-Service-Tenant-ID"]["required"] is True
    assert headers["X-Service-Auth"]["required"] is True


def test_aivan_assessment_scope_is_preserved_in_normalized_and_persisted_input() -> None:
    request = GLTGSimulationRequestV2.model_validate(
        _payload(
            case_context={
                "assessment_scope": "supplier_candidate",
                "supplier_id": "SUP-1",
            }
        )
    )

    assert request.case_context.assessment_scope == "supplier_candidate"
    assert request.model_dump(mode="json")["case_context"] == {
        "procurement_case_id": None,
        "rfq_id": None,
        "quote_id": None,
        "po_id": None,
        "buyer_id": None,
        "supplier_id": "SUP-1",
        "assessment_scope": "supplier_candidate",
    }


def test_invalid_aivan_assessment_scope_is_rejected() -> None:
    with pytest.raises(ValueError):
        GLTGSimulationRequestV2.model_validate(
            _payload(case_context={"assessment_scope": "untrusted-scope"})
        )


def test_non_ascii_raw_auth_is_401_before_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden_pipeline(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        raise AssertionError("unauthenticated request reached the calculation pipeline")

    monkeypatch.setattr(routes, "run_simulation", forbidden_pipeline)
    body = json.dumps(_payload()).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v2/lead-time/simulate",
        "raw_path": b"/v2/lead-time/simulate",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"x-service-tenant-id", TENANT.encode()),
            (b"x-service-auth", b"\xff"),
        ],
        "client": ("127.0.0.1", 54321),
        "server": ("testserver", 80),
    }
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(item for item in messages if item["type"] == "http.response.start")
    response_body = b"".join(
        item.get("body", b"")
        for item in messages
        if item["type"] == "http.response.body"
    )
    assert start["status"] == 401
    assert json.loads(response_body) == {
        "error": "CALLER_AUTH_INVALID",
        "code": "CALLER_AUTH_INVALID",
    }
    assert calls == 0


class _TenantBoundEvidenceClient:
    def __init__(self) -> None:
        self.tenants: list[str] = []

    def get_supplier(self, supplier_id: str, tenant_id: str) -> dict[str, Any]:
        self.tenants.append(tenant_id)
        return {"supplier_id": supplier_id, "tenant_id": tenant_id}

    def get_supplier_behavior_summary(
        self, supplier_id: str, tenant_id: str
    ) -> dict[str, Any]:
        self.tenants.append(tenant_id)
        return {
            "supplier_id": supplier_id,
            "tenant_id": tenant_id,
            "observation_count": 1,
            "latest_snapshot": {
                "snapshot_id": "SNAP-1",
                "source_observation_ids_json": ["OBS-OWNED"],
                "feature_json": {},
            },
        }

    def persist_gltg_run(self, payload: dict[str, Any], tenant_id: str) -> dict[str, Any]:
        raise AssertionError("persistence is disabled in this contract test")


def test_provider_rejects_unowned_source_observation_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _TenantBoundEvidenceClient()
    monkeypatch.setattr(v2_pipeline, "client_from_env", lambda: provider)
    response = TestClient(app).post(
        "/v2/lead-time/simulate",
        json=_payload(
            source_observation_ids=["OBS-FOREIGN"],
            evidence={"use_giraffe_db": True},
        ),
        headers=HEADERS,
    )
    assert response.status_code == 403
    assert response.json() == {
        "error": "EVIDENCE_REFERENCE_FORBIDDEN",
        "code": "EVIDENCE_REFERENCE_FORBIDDEN",
    }
    assert provider.tenants == [TENANT, TENANT]


def test_provider_accepts_owned_source_observation_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _TenantBoundEvidenceClient()
    monkeypatch.setattr(v2_pipeline, "client_from_env", lambda: provider)
    response = TestClient(app).post(
        "/v2/lead-time/simulate",
        json=_payload(
            source_observation_ids=["OBS-OWNED"],
            evidence={"use_giraffe_db": True},
        ),
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert "OBS-OWNED" in response.json()["source_observation_ids"]
    assert provider.tenants == [TENANT, TENANT]


def test_configured_db_without_outbound_auth_is_explicitly_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GLTG_GIRAFFE_DB_BASE_URL", "http://giraffe-db.test")
    monkeypatch.delenv("GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET", raising=False)
    response = TestClient(app).post(
        "/v2/lead-time/simulate",
        json=_payload(evidence={"use_giraffe_db": True}),
        headers=HEADERS,
    )
    assert response.status_code == 503
    assert response.json()["code"] == "DB_UNAVAILABLE"
    assert "auth" in response.json()["error"].lower()


def test_ready_reports_missing_outbound_auth_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GLTG_GIRAFFE_DB_BASE_URL", "http://giraffe-db.test")
    monkeypatch.delenv("GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET", raising=False)
    response = TestClient(app).get("/ready")
    assert response.status_code == 200
    assert response.json()["ready"] is False
    assert response.json()["giraffe_db"] == "auth_not_configured"
