"""Shared fixtures and helpers for the GLTG test suite."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from gltg.models.capability import Capability
from gltg.models.enums import ApparelNodeType, ParticipantType
from gltg.models.order import ApparelOrderInput
from gltg.models.participant import ParticipantProfile


TEST_INBOUND_SECRET = "test-inbound-secret"
TEST_EXPLICIT_IDENTITY_HEADER = "X-GLTG-Test-Explicit-Identity"


@pytest.fixture(autouse=True)
def _authenticated_v2_test_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run legacy positive API tests through the required service boundary.

    Tests that exercise missing identity set the private test-only sentinel and
    provide their exact headers. The sentinel is removed before the request is
    sent and is never part of the product API.
    """

    monkeypatch.setenv("GLTG_INBOUND_SERVICE_AUTH_SECRET", TEST_INBOUND_SECRET)
    original_request = TestClient.request

    def authenticated_request(
        self: TestClient, method: str, url: str, **kwargs: Any
    ):
        headers = dict(kwargs.pop("headers", {}) or {})
        explicit = headers.pop(TEST_EXPLICIT_IDENTITY_HEADER, None) == "1"
        if str(url).startswith("/v2/") and not explicit:
            headers.setdefault("X-Service-Auth", TEST_INBOUND_SECRET)
            body = kwargs.get("json")
            tenant_id = ""
            if isinstance(body, dict):
                if isinstance(body.get("tenant_id"), str):
                    tenant_id = body["tenant_id"]
                elif isinstance(body.get("simulations"), list) and body["simulations"]:
                    first = body["simulations"][0]
                    if isinstance(first, dict) and isinstance(first.get("tenant_id"), str):
                        tenant_id = first["tenant_id"]
            headers.setdefault("X-Service-Tenant-ID", tenant_id or "tenant_default")
        return original_request(self, method, url, headers=headers, **kwargs)

    monkeypatch.setattr(TestClient, "request", authenticated_request)


def make_participant(pid, ptype=ParticipantType.GARMENT_FACTORY, node_types=None):
    """Create a ParticipantProfile with capabilities for the given node types."""
    if node_types is None:
        node_types = [
            ApparelNodeType.CUTTING,
            ApparelNodeType.SEWING,
            ApparelNodeType.PACKING,
        ]
    caps = [
        Capability(
            capability_id=f"{pid}-{nt.value[:4]}",
            node_type=nt,
            capacity_per_day=500,
            typical_lead_days=5,
        )
        for nt in node_types
    ]
    return ParticipantProfile(
        participant_id=pid,
        name=f"Participant {pid}",
        participant_type=ptype,
        capabilities=caps,
        reliability_score=0.85,
        on_time_delivery_rate=0.85,
    )


def make_order(order_id="TEST-001", quantity=1000, participants=None, requested_date=None):
    """Create a minimal ApparelOrderInput."""
    return ApparelOrderInput(
        order_id=order_id,
        product_type="men_shirt_cotton",
        quantity=quantity,
        requested_delivery_date=requested_date,
        dynamic_form={"fabric_type": "cotton"},
        participants=participants or [],
    )


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def three_participants():
    """Three distinct GARMENT_FACTORY participants."""
    return [
        make_participant("P1"),
        make_participant("P2"),
        make_participant("P3"),
    ]


@pytest.fixture
def base_order(three_participants):
    """A standard order with three participants and a requested date."""
    return make_order(
        participants=three_participants,
        requested_date=date(2026, 12, 31),
    )
