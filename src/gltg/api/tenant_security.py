"""Fail-closed inbound service identity and tenant binding for v2 routes."""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterable


class InboundIdentityError(Exception):
    """Stable, non-secret-bearing inbound authentication failure."""

    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def require_tenant_identity(
    tenant_header: str | None,
    auth_header: str | None,
    tenant_ids: Iterable[str],
) -> str:
    """Authenticate the caller and bind all body tenants to its tenant header.

    ``X-Service-Tenant-ID`` is authoritative only after ``X-Service-Auth`` has
    been validated against the dedicated inbound secret. Body tenant values
    are mandatory assertions and can never select a different tenant.
    """

    tenant_id = (tenant_header or "").strip()
    if not tenant_id:
        raise InboundIdentityError("TENANT_CONTEXT_REQUIRED", 401)

    supplied_secret = auth_header or ""
    if not supplied_secret:
        raise InboundIdentityError("CALLER_AUTH_REQUIRED", 401)

    expected_secret = os.environ.get("GLTG_INBOUND_SERVICE_AUTH_SECRET", "").strip()
    if not expected_secret:
        raise InboundIdentityError("CALLER_AUTH_UNAVAILABLE", 503)
    if not secrets.compare_digest(supplied_secret, expected_secret):
        raise InboundIdentityError("CALLER_AUTH_INVALID", 401)

    if any(body_tenant != tenant_id for body_tenant in tenant_ids):
        raise InboundIdentityError("TENANT_CONTEXT_MISMATCH", 403)
    return tenant_id


__all__ = ["InboundIdentityError", "require_tenant_identity"]
