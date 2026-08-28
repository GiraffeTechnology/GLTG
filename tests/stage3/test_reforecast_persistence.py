"""PR #8 review fix: reforecast persistence must serialize the UPDATED request.

Proves: applied events change the updated request; the persisted
``behavior_input_json`` carries the post-event values; persisted quantiles
equal the reforecast response; replaying the persisted ``request_json``
reproduces the output; the original request is never mutated; applied and
unapplied events are auditable and distinct.
"""

from __future__ import annotations

import copy
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from gltg.api.main import app
from gltg.behavioral.schemas import GLTGSimulationRequestV2
from gltg.behavioral.simulator import BehavioralLeadTimeSimulator
from gltg.services.v2_pipeline import _request_fingerprint

client = TestClient(
    app,
    headers={
        "X-Service-Auth": "test-inbound-secret",
        "X-Service-Tenant-ID": "tenant-demo",
    },
)
BASE = "http://giraffe-db.test"
TENANT = "tenant-demo"

DELAY_EVENT = {
    "event_type": "supplier_response_delay",
    "response_delay_ratio": 3.5,
    "source_observation_ids": ["GDB_SYN_V1_OBS_000002"],
}
UNKNOWN_EVENT = {"event_type": "alien_event", "x": 1}


def _payload() -> dict:
    return {
        "request_id": "REF-PERSIST-1",
        "tenant_id": TENANT,
        "order": {"product_type": "t-shirt", "quantity": 5000, "deadline_days": 150},
        "supplier": {
            "supplier_id": "GDB_SYN_V1_SUP_000001",
            "capacity_per_day": 500,
            "material_ready_days": 7,
            "production_days": 12,
            "qc_days": 3,
            "logistics_days": 18,
            "confidence": 0.75,
        },
        "source_observation_ids": ["GDB_SYN_V1_OBS_000001"],
        "events": [DELAY_EVENT, UNKNOWN_EVENT],
    }


@pytest.fixture()
def persisted(monkeypatch):
    monkeypatch.setenv("GLTG_GIRAFFE_DB_BASE_URL", BASE)
    monkeypatch.setenv("GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET", "s3cret")
    monkeypatch.setenv("GLTG_PERSIST_RUNS", "true")
    payload = _payload()
    original_snapshot = copy.deepcopy(payload)
    with respx.mock:
        route = respx.post(f"{BASE}/api/data/gltg-simulation-runs").mock(
            return_value=httpx.Response(
                200, json={"gltg_run_id": "GDB_SYN_V1_GLTG_000042", "tenant_id": TENANT}
            )
        )
        response = client.post("/v2/reforecast", json=payload)
    assert response.status_code == 200
    body = response.json()
    stored = json.loads(route.calls[0].request.content)
    return payload, original_snapshot, body, stored


def test_event_changes_updated_request_and_is_persisted(persisted) -> None:
    _, _, body, stored = persisted
    # 1. the event changed the updated request; 2. persisted inputs carry it
    assert stored["behavior_input_json"]["supplier"]["response_delay_ratio"] == 3.5
    assert (
        stored["base_input_json"]["request_json"]["behavior_features"]["supplier"][
            "response_delay_ratio"
        ]
        == 3.5
    )
    assert body["applied_events"] == [DELAY_EVENT]


def test_persisted_quantiles_equal_response(persisted) -> None:
    _, _, body, stored = persisted
    assert stored["final_p50_days"] == body["quantiles"]["p50_days"]
    assert stored["final_p80_days"] == body["quantiles"]["p80_days"]
    assert stored["final_p90_days"] == body["quantiles"]["p90_days"]
    assert stored["output_json"]["quantiles"] == body["quantiles"]


def test_replaying_persisted_request_reproduces_output(persisted) -> None:
    _, _, body, stored = persisted
    replay_req = GLTGSimulationRequestV2.model_validate(
        stored["base_input_json"]["request_json"]
    )
    replayed = BehavioralLeadTimeSimulator().simulate(replay_req)
    assert replayed.quantiles.model_dump() == body["quantiles"]
    assert stored["base_input_json"]["input_fingerprint"] == _request_fingerprint(replay_req)


def test_original_request_not_mutated(persisted) -> None:
    payload, original_snapshot, _, stored = persisted
    assert payload == original_snapshot
    # And the persisted request is genuinely different from the original input
    assert (
        original_snapshot.get("behavior_features", {})
        .get("supplier", {})
        .get("response_delay_ratio")
        is None
    )


def test_event_audit_trail_distinguishes_applied_and_unapplied(persisted) -> None:
    _, _, body, stored = persisted
    meta = stored["base_input_json"]["reforecast_meta"]
    assert meta["reforecast"] is True
    assert meta["applied_events"] == [DELAY_EVENT]
    assert meta["unapplied_events"] == [UNKNOWN_EVENT]
    assert meta["triggering_observation_ids"] == ["GDB_SYN_V1_OBS_000002"]
    assert meta["previous_run_id"].startswith("GLTG_")
    assert meta["previous_run_id"] != body["gltg_run_id"]
    # unapplied events never masquerade as applied
    assert UNKNOWN_EVENT not in meta["applied_events"]
    assert body["unapplied_events"] == [UNKNOWN_EVENT]


def test_simulate_persistence_also_carries_fingerprint(monkeypatch) -> None:
    monkeypatch.setenv("GLTG_GIRAFFE_DB_BASE_URL", BASE)
    monkeypatch.setenv("GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET", "s3cret")
    monkeypatch.setenv("GLTG_PERSIST_RUNS", "true")
    payload = {key: value for key, value in _payload().items() if key != "events"}
    with respx.mock:
        route = respx.post(f"{BASE}/api/data/gltg-simulation-runs").mock(
            return_value=httpx.Response(
                200, json={"gltg_run_id": "GDB_SYN_V1_GLTG_000043", "tenant_id": TENANT}
            )
        )
        body = client.post("/v2/lead-time/simulate", json=payload).json()
    stored = json.loads(route.calls[0].request.content)
    assert "request_json" in stored["base_input_json"]
    assert "input_fingerprint" in stored["base_input_json"]
    assert "reforecast_meta" not in stored["base_input_json"]
    assert stored["final_p50_days"] == body["quantiles"]["p50_days"]
