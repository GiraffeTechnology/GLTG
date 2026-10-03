from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from gltg.api.main import app
from gltg.integrations.giraffe_db_client import (
    GiraffeDBAuthError,
    GiraffeDBClient,
    GiraffeDBNotConfigured,
    client_from_env,
)

INBOUND_SECRET = "test-inbound-secret"
TENANT = "tenant-a"
HEADERS = {"X-Service-Auth": INBOUND_SECRET, "X-Service-Tenant-ID": TENANT}
BASE = "http://giraffe-db.test"
SUPPLIER = "SUP-1"


def _payload(**overrides: object) -> dict:
    payload = {
        "request_id": "S1-TENANT-1",
        "tenant_id": TENANT,
        "order": {"product_type": "apparel", "quantity": 100},
        "supplier": {"supplier_id": SUPPLIER},
    }
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def _inbound_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLTG_INBOUND_SERVICE_AUTH_SECRET", INBOUND_SECRET)
    monkeypatch.delenv("GLTG_PERSIST_RUNS", raising=False)
    monkeypatch.delenv("GLTG_GIRAFFE_DB_BASE_URL", raising=False)
    monkeypatch.delenv("GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET", raising=False)


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({"X-Service-Auth": INBOUND_SECRET}, "TENANT_CONTEXT_REQUIRED"),
        ({"X-Service-Auth": INBOUND_SECRET, "X-Service-Tenant-ID": "   "}, "TENANT_CONTEXT_REQUIRED"),
        ({"X-Service-Tenant-ID": TENANT}, "CALLER_AUTH_REQUIRED"),
        ({"X-Service-Tenant-ID": TENANT, "X-Service-Auth": "wrong"}, "CALLER_AUTH_INVALID"),
    ],
)
def test_missing_blank_or_invalid_identity_fails_closed(headers: dict[str, str], code: str) -> None:
    response = TestClient(app).post("/v2/lead-time/simulate", json=_payload(), headers=headers)
    assert response.status_code in {401, 403}
    assert response.json() == {"error": code, "code": code}


def test_body_tenant_is_not_trusted_when_authenticated_tenant_differs() -> None:
    response = TestClient(app).post(
        "/v2/lead-time/simulate", json=_payload(tenant_id="tenant-spoofed"), headers=HEADERS
    )
    assert response.status_code == 403
    assert response.json()["code"] == "TENANT_CONTEXT_MISMATCH"


def test_body_tenant_is_mandatory_even_with_authenticated_header() -> None:
    payload = _payload()
    payload.pop("tenant_id")
    response = TestClient(app).post("/v2/lead-time/simulate", json=payload, headers=HEADERS)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_authenticated_matching_tenant_is_accepted() -> None:
    response = TestClient(app).post("/v2/lead-time/simulate", json=_payload(), headers=HEADERS)
    assert response.status_code == 200


def test_openapi_marks_tenant_identity_headers_required() -> None:
    operation = app.openapi()["paths"]["/v2/lead-time/simulate"]["post"]
    headers = {item["name"]: item for item in operation["parameters"]}
    assert headers["X-Service-Tenant-ID"]["required"] is True
    assert headers["X-Service-Auth"]["required"] is True


def test_configured_db_without_service_secret_fails_before_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLTG_GIRAFFE_DB_BASE_URL", BASE)
    monkeypatch.delenv("GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET", raising=False)
    with pytest.raises(GiraffeDBNotConfigured, match="service auth"):
        client_from_env()


@pytest.mark.parametrize("operation", ["supplier", "summary", "persistence"])
def test_cross_tenant_db_response_is_rejected(operation: str) -> None:
    client = GiraffeDBClient(BASE, "db-secret")
    path = {
        "supplier": f"/api/data/suppliers/{SUPPLIER}",
        "summary": f"/api/data/suppliers/{SUPPLIER}/behavior-summary",
        "persistence": "/api/data/gltg-simulation-runs",
    }[operation]
    response_payload = {
        "supplier": {"supplier_id": SUPPLIER, "tenant_id": "tenant-b"},
        "summary": {"supplier_id": SUPPLIER, "tenant_id": "tenant-b", "observation_count": 0},
        "persistence": {"gltg_run_id": "RUN-1", "tenant_id": "tenant-b"},
    }[operation]
    with respx.mock:
        route = respx.post(f"{BASE}{path}") if operation == "persistence" else respx.get(f"{BASE}{path}")
        route.mock(return_value=httpx.Response(200, json=response_payload))
        with pytest.raises(GiraffeDBAuthError, match="tenant"):
            if operation == "supplier":
                client.get_supplier(SUPPLIER, TENANT)
            elif operation == "summary":
                client.get_supplier_behavior_summary(SUPPLIER, TENANT)
            else:
                client.persist_gltg_run({}, TENANT)


def test_non_ascii_auth_bytes_fail_closed_before_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline_calls = 0

    def forbidden_pipeline(*args: object, **kwargs: object) -> None:
        nonlocal pipeline_calls
        pipeline_calls += 1
        raise AssertionError("pipeline must not run")

    monkeypatch.setattr("gltg.api.routes.run_simulation", forbidden_pipeline)
    payload = json.dumps(_payload()).encode("utf-8")
    messages: list[dict[str, object]] = []
    request_sent = False

    async def receive() -> dict[str, object]:
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v2/lead-time/simulate",
        "raw_path": b"/v2/lead-time/simulate",
        "query_string": b"",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode("ascii")),
            (b"x-service-tenant-id", TENANT.encode("ascii")),
            (b"x-service-auth", b"invalid-\xff-auth"),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8090),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    assert start["status"] == 401
    assert json.loads(body) == {"error": "CALLER_AUTH_INVALID", "code": "CALLER_AUTH_INVALID"}
    assert pipeline_calls == 0
