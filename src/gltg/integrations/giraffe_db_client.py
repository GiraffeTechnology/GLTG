"""Authenticated giraffe-db evidence client.

giraffe-db is the canonical evidence service. This client retrieves
tenant-scoped supplier evidence and persists GLTG runs over real HTTP with
service auth headers. It has **no mock fallback**: when giraffe-db is not
configured or not reachable, callers receive explicit, typed errors — GLTG
never silently substitutes guessed local values for required evidence.

Configuration (environment):

    GLTG_GIRAFFE_DB_BASE_URL             e.g. http://giraffe-db:8000
    GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET  sent as X-Service-Auth (redacted in repr/logs)
    GLTG_GIRAFFE_DB_TIMEOUT_SECONDS      default 5

The tenant ID is passed per call and propagated as X-Service-Tenant-ID.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_TIMEOUT_SECONDS = 5.0

# Stable error codes surfaced to API consumers.
CODE_DB_UNAVAILABLE = "DB_UNAVAILABLE"
CODE_AUTH_FAILED = "EVIDENCE_AUTH_FAILED"
CODE_NOT_FOUND = "EVIDENCE_NOT_FOUND"
CODE_MALFORMED = "EVIDENCE_MALFORMED"
CODE_NOT_CONFIGURED = "GIRAFFE_DB_NOT_CONFIGURED"


class GiraffeDBError(Exception):
    """Base class for giraffe-db evidence errors; carries a stable code."""

    code = CODE_DB_UNAVAILABLE

    def __init__(self, message: str) -> None:
        super().__init__(message)


class GiraffeDBNotConfigured(GiraffeDBError):
    code = CODE_NOT_CONFIGURED


class GiraffeDBUnavailable(GiraffeDBError):
    code = CODE_DB_UNAVAILABLE


class GiraffeDBAuthError(GiraffeDBError):
    code = CODE_AUTH_FAILED


class GiraffeDBNotFound(GiraffeDBError):
    code = CODE_NOT_FOUND


class GiraffeDBMalformedResponse(GiraffeDBError):
    code = CODE_MALFORMED


class GiraffeDBClient:
    """Minimal, bounded, tenant-scoped giraffe-db HTTP client."""

    def __init__(
        self,
        base_url: str,
        service_auth_secret: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._secret = service_auth_secret
        self.timeout_seconds = timeout_seconds

    def __repr__(self) -> str:  # never leak the secret
        return (
            f"GiraffeDBClient(base_url={self.base_url!r}, "
            f"auth={'***' if self._secret else 'unset'}, "
            f"timeout={self.timeout_seconds})"
        )

    # ------------------------------------------------------------------ #
    # Transport
    # ------------------------------------------------------------------ #
    def _headers(self, tenant_id: str) -> dict[str, str]:
        headers = {"X-Service-Tenant-ID": tenant_id}
        if self._secret:
            headers["X-Service-Auth"] = self._secret
        return headers

    def _request(
        self,
        method: str,
        path: str,
        tenant_id: str,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = httpx.request(
                method,
                url,
                headers=self._headers(tenant_id),
                json=json_body,
                timeout=self.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise GiraffeDBUnavailable(
                f"giraffe-db unreachable ({type(exc).__name__}) at {url}"
            ) from exc
        if response.status_code in (401, 403):
            raise GiraffeDBAuthError(
                f"giraffe-db rejected service auth/tenant (HTTP {response.status_code})"
            )
        if response.status_code == 404:
            raise GiraffeDBNotFound(f"giraffe-db has no record at {path}")
        if response.status_code >= 500:
            raise GiraffeDBUnavailable(f"giraffe-db error HTTP {response.status_code}")
        if response.status_code >= 400:
            raise GiraffeDBMalformedResponse(
                f"giraffe-db rejected the request (HTTP {response.status_code}): "
                f"{response.text[:300]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise GiraffeDBMalformedResponse("giraffe-db returned non-JSON body") from exc

    # ------------------------------------------------------------------ #
    # Evidence retrieval
    # ------------------------------------------------------------------ #
    def get_supplier(self, supplier_id: str, tenant_id: str) -> dict[str, Any]:
        data = self._request("GET", f"/api/data/suppliers/{supplier_id}", tenant_id)
        if not isinstance(data, dict) or data.get("supplier_id") != supplier_id:
            raise GiraffeDBMalformedResponse(
                "supplier record failed validation (missing/mismatched supplier_id)"
            )
        return data

    def get_supplier_behavior_summary(self, supplier_id: str, tenant_id: str) -> dict[str, Any]:
        data = self._request(
            "GET", f"/api/data/suppliers/{supplier_id}/behavior-summary", tenant_id
        )
        if not isinstance(data, dict) or data.get("supplier_id") != supplier_id:
            raise GiraffeDBMalformedResponse(
                "behavior summary failed validation (missing/mismatched supplier_id)"
            )
        return data

    # ------------------------------------------------------------------ #
    # Run persistence
    # ------------------------------------------------------------------ #
    def persist_gltg_run(self, payload: dict[str, Any], tenant_id: str) -> dict[str, Any]:
        data = self._request("POST", "/api/data/gltg-simulation-runs", tenant_id, payload)
        if not isinstance(data, dict) or not data.get("gltg_run_id"):
            raise GiraffeDBMalformedResponse(
                "gltg run persistence response failed validation (no gltg_run_id)"
            )
        return data

    def healthz(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/healthz", timeout=self.timeout_seconds)
        except (httpx.TimeoutException, httpx.TransportError):
            return False
        return response.status_code == 200


def client_from_env() -> GiraffeDBClient | None:
    """Build a client from the environment, or None when not configured."""

    base_url = os.environ.get("GLTG_GIRAFFE_DB_BASE_URL", "").strip()
    if not base_url:
        return None
    timeout_raw = os.environ.get("GLTG_GIRAFFE_DB_TIMEOUT_SECONDS", "")
    try:
        timeout = float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        timeout = DEFAULT_TIMEOUT_SECONDS
    return GiraffeDBClient(
        base_url=base_url,
        service_auth_secret=os.environ.get("GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET") or None,
        timeout_seconds=timeout,
    )


__all__ = [
    "GiraffeDBClient",
    "GiraffeDBError",
    "GiraffeDBNotConfigured",
    "GiraffeDBUnavailable",
    "GiraffeDBAuthError",
    "GiraffeDBNotFound",
    "GiraffeDBMalformedResponse",
    "client_from_env",
    "CODE_DB_UNAVAILABLE",
    "CODE_AUTH_FAILED",
    "CODE_NOT_FOUND",
    "CODE_MALFORMED",
    "CODE_NOT_CONFIGURED",
]
