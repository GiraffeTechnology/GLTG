"""PR #8 review fix: unusable behavior evidence must reduce confidence.

Covers behavior summary 404, malformed payload, missing required fields,
empty summary (zero observations), and behavior endpoint unavailable while
the supplier read succeeded — each with a bounded penalty, stable codes,
confidence within [0,1], and no invented behavior or observation IDs. Auth
failures still fail closed.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from gltg.api.main import app
from gltg.services.v2_pipeline import (
    BEHAVIOR_EVIDENCE_PENALTY,
    MAX_EVIDENCE_CONFIDENCE_PENALTY,
)

client = TestClient(app)
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
HEALTHY_SUMMARY = {
    "supplier_id": SUPPLIER_ID,
    "observation_count": 12,
    "latest_snapshot": {
        "snapshot_id": "GDB_SYN_V1_SUPFEAT_000001",
        "feature_json": {},
    },
    "response_delay": {"response_delay_ratio": None},
}


def _payload() -> dict:
    return {
        "request_id": "PEN-1",
        "tenant_id": TENANT,
        "order": {"product_type": "t-shirt", "quantity": 1000, "deadline_days": 150},
        "supplier": {"supplier_id": SUPPLIER_ID, "capacity_per_day": 500, "confidence": 0.8},
        "evidence": {"use_giraffe_db": True},
        "source_observation_ids": ["GDB_SYN_V1_OBS_000001"],
    }


@pytest.fixture(autouse=True)
def gdb_env(monkeypatch):
    monkeypatch.setenv("GLTG_GIRAFFE_DB_BASE_URL", BASE)
    monkeypatch.setenv("GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET", "s3cret")
    monkeypatch.delenv("GLTG_PERSIST_RUNS", raising=False)


def _simulate_with_summary_response(summary_response) -> dict:
    with respx.mock:
        respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}").mock(
            return_value=httpx.Response(200, json=SUPPLIER_RECORD)
        )
        route = respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}/behavior-summary")
        if isinstance(summary_response, Exception):
            route.mock(side_effect=summary_response)
        else:
            route.mock(return_value=summary_response)
        response = client.post("/v2/lead-time/simulate", json=_payload())
    assert response.status_code == 200
    return response.json()


def _baseline_confidence() -> float:
    body = _simulate_with_summary_response(httpx.Response(200, json=HEALTHY_SUMMARY))
    codes = {w["code"] for w in body["warnings"]}
    assert "MISSING_BEHAVIOR_EVIDENCE" not in codes
    assert body["explanation_json"]["evidence"]["behavior_evidence_status"] == "ok"
    return body["risk"]["confidence_score"]


DEGRADED_CASES = {
    "not_found_404": (
        httpx.Response(404, json={"detail": {"error": "not_found"}}),
        "endpoint_not_found",
    ),
    "malformed_payload": (
        httpx.Response(200, json={"unexpected": "shape"}),
        "malformed_payload",
    ),
    "missing_required_fields": (
        httpx.Response(200, json={"supplier_id": SUPPLIER_ID, "latest_snapshot": None}),
        "malformed_payload",
    ),
    "empty_summary": (
        httpx.Response(
            200,
            json={
                "supplier_id": SUPPLIER_ID,
                "observation_count": 0,
                "latest_snapshot": None,
                "response_delay": {"response_delay_ratio": None},
            },
        ),
        "no_observations",
    ),
    "endpoint_unavailable_supplier_ok": (
        httpx.ConnectError("behavior endpoint down"),
        "endpoint_unavailable",
    ),
}


@pytest.mark.parametrize("case", DEGRADED_CASES, ids=list(DEGRADED_CASES))
def test_unusable_behavior_evidence_lowers_confidence(case) -> None:
    summary_response, expected_status = DEGRADED_CASES[case]
    baseline = _baseline_confidence()
    body = _simulate_with_summary_response(summary_response)

    codes = {w["code"] for w in body["warnings"]}
    assert "MISSING_BEHAVIOR_EVIDENCE" in codes
    assert body["explanation_json"]["evidence"]["behavior_evidence_status"] == expected_status

    confidence = body["risk"]["confidence_score"]
    assert confidence == pytest.approx(baseline - BEHAVIOR_EVIDENCE_PENALTY, abs=1e-6)
    assert 0.0 <= confidence <= 1.0

    # Explanation records the bounded penalty with the specific reason.
    adjustments = [
        adj for adj in body["explanation_json"]["adjustments"]
        if adj["feature"] == "missing_evidence"
    ]
    assert adjustments and expected_status in adjustments[0]["reason"]
    assert adjustments[0]["value"] <= MAX_EVIDENCE_CONFIDENCE_PENALTY

    # No invented behavior or observation IDs.
    assert body["source_observation_ids"] == ["GDB_SYN_V1_OBS_000001"]
    assert body["quantiles"] == _simulate_without_evidence()["quantiles"]


def _simulate_without_evidence() -> dict:
    payload = _payload()
    payload["evidence"] = {"use_giraffe_db": False}
    return client.post("/v2/lead-time/simulate", json=payload).json()


def test_valid_evidence_keeps_baseline_confidence() -> None:
    baseline = _baseline_confidence()
    no_evidence = _simulate_without_evidence()["risk"]["confidence_score"]
    # healthy evidence never scores below the evidence-free run
    assert baseline >= no_evidence - 1e-9


def test_penalty_is_bounded_even_when_stacked() -> None:
    # Supplier not found (0.1) would stack with behavior penalty paths; the
    # applied total is capped at MAX_EVIDENCE_CONFIDENCE_PENALTY and the final
    # confidence stays within [0, 1].
    with respx.mock:
        respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}").mock(
            return_value=httpx.Response(404, json={"detail": {"error": "not_found"}})
        )
        body = client.post("/v2/lead-time/simulate", json=_payload()).json()
    assert 0.0 <= body["risk"]["confidence_score"] <= 1.0
    adjustments = [
        adj for adj in body["explanation_json"].get("adjustments", [])
        if adj["feature"] == "missing_evidence"
    ]
    assert adjustments and adjustments[0]["value"] <= MAX_EVIDENCE_CONFIDENCE_PENALTY


def test_auth_failure_on_behavior_summary_still_fails_closed() -> None:
    with respx.mock:
        respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}").mock(
            return_value=httpx.Response(200, json=SUPPLIER_RECORD)
        )
        respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER_ID}/behavior-summary").mock(
            return_value=httpx.Response(403, json={"detail": {"error": "forbidden"}})
        )
        response = client.post("/v2/lead-time/simulate", json=_payload())
    assert response.status_code == 502
    assert response.json()["code"] == "EVIDENCE_AUTH_FAILED"


def test_missing_evidence_never_increases_confidence() -> None:
    baseline = _baseline_confidence()
    for summary_response, _ in DEGRADED_CASES.values():
        body = _simulate_with_summary_response(summary_response)
        assert body["risk"]["confidence_score"] <= baseline
