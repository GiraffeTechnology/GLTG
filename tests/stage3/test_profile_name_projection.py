"""Profile display text stays out of process inputs; replay remains complete."""
from __future__ import annotations

import copy
import hashlib

import pytest

from gltg.behavioral.schemas import GLTGSimulationRequestV2
from gltg.behavioral.simulator import BehavioralLeadTimeSimulator
from gltg.services.v2_pipeline import _request_fingerprint, persist_run, resolve_evidence

SUPPLIER_ID = "GDB_SYN_V1_SUP_000001"
TENANT = "tenant-demo"


class SyntheticProvider:
    def __init__(self, name):
        self.name = name
        self.persisted = None

    def get_supplier(self, supplier_id, tenant_id):
        assert (supplier_id, tenant_id) == (SUPPLIER_ID, TENANT)
        return {"supplier_id": supplier_id, "tenant_id": tenant_id,
                "name_en": self.name, "supplier_name": self.name, "is_synthetic": True}

    def get_supplier_behavior_summary(self, supplier_id, tenant_id):
        return {"supplier_id": supplier_id, "tenant_id": tenant_id,
                "observation_count": 0, "latest_snapshot": None,
                "response_delay": {"response_delay_ratio": None}}

    def persist_gltg_run(self, payload, tenant_id):
        self.persisted = copy.deepcopy(payload)
        return {"gltg_run_id": "GDB_SYN_V1_GLTG_000001", "tenant_id": tenant_id}


def request(name=None):
    return GLTGSimulationRequestV2.model_validate({
        "request_id": "PROFILE-1", "tenant_id": TENANT,
        "order": {"product_type": "t-shirt", "quantity": 5000, "deadline_days": 150},
        "supplier": {"supplier_id": SUPPLIER_ID, "name": name, "capacity_per_day": 500},
        "evidence": {"use_giraffe_db": True},
    })


@pytest.mark.parametrize("profile_name", [
    "PT Sinar Apparel (Bandung)", "\u5408\u6210\u4f9b\u5e94\u5546",
])
def test_profile_name_is_referenced_and_hashed_without_copying_into_process(profile_name, monkeypatch):
    monkeypatch.setenv("GLTG_PERSIST_RUNS", "true")
    req = request()
    original = req.model_dump(mode="json")
    provider = SyntheticProvider(profile_name)
    evidence = resolve_evidence(req, provider)
    assert req.model_dump(mode="json") == original
    assert req.supplier.name is None
    metadata = evidence.explanation["evidence"]
    assert metadata["supplier_id"] == SUPPLIER_ID
    assert metadata["supplier_profile_name_sha256"] == hashlib.sha256(profile_name.encode()).hexdigest()
    assert profile_name not in str(metadata)

    simulator = BehavioralLeadTimeSimulator()
    response = simulator.simulate(req)
    response.explanation_json.update(evidence.explanation)
    persist_run(req, response, provider)
    persisted = provider.persisted
    replay_req = GLTGSimulationRequestV2.model_validate(persisted["base_input_json"]["request_json"])
    assert replay_req.model_dump(mode="json") == original
    assert persisted["base_input_json"]["input_fingerprint"] == _request_fingerprint(replay_req)
    replay = simulator.simulate(replay_req)
    assert replay.quantiles == response.quantiles
    assert replay.components == response.components
    assert replay.risk == response.risk
    # The old display enrichment was not a quantitative model input.
    old_display_request = req.model_copy(deep=True)
    old_display_request.supplier.name = profile_name
    old_display_response = simulator.simulate(old_display_request)
    assert old_display_response.quantiles == response.quantiles
    assert old_display_response.components == response.components
    assert old_display_response.risk == response.risk


def test_profile_enrichment_does_not_rewrite_caller_input():
    req = request("Caller supplied supplier name")
    original = req.model_dump(mode="json")
    resolve_evidence(req, SyntheticProvider("Different profile display name"))
    assert req.model_dump(mode="json") == original
