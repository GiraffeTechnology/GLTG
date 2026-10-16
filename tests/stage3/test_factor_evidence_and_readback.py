import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from gltg.api.main import app
from gltg.behavioral.schemas import GLTGSimulationRequestV2
from gltg.integrations.giraffe_db_client import GiraffeDBClient
from gltg.services.v2_pipeline import resolve_evidence

BASE = "http://provider.test"
TENANT = "tenant-a"
SUPPLIER = "supplier-1"


def payload():
    return {"request_id": "EVIDENCE-1", "tenant_id": TENANT,
            "order": {"quantity": 100}, "supplier": {"supplier_id": SUPPLIER},
            "case_context": {"procurement_case_id": "case-1"},
            "evidence": {"use_giraffe_db": True}}


def setup_provider(features):
    respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER}").respond(
        200, json={"tenant_id": TENANT, "supplier_id": SUPPLIER})
    respx.get(f"{BASE}/api/data/suppliers/{SUPPLIER}/behavior-summary").respond(
        200, json={"tenant_id": TENANT, "supplier_id": SUPPLIER, "observation_count": 2,
                   "latest_snapshot": {"snapshot_id": "snapshot-1", "tenant_id": TENANT,
                                       "supplier_id": SUPPLIER, "feature_json": features,
                                       "source_observation_ids_json": ["obs-1"]}})


@respx.mock
def test_provider_trade_factors_and_source_lineage_enter_evaluated_input():
    setup_provider({"material_availability_status": "partial_stock", "stock_coverage_ratio": .25,
                    "raw_material_lead_time_estimate_days": 8,
                    "supplier_execution_mode": "in_house_manufacturer",
                    "trade_processing_factors": {"processing": {"sample_required": True, "sample_days": 2}}})
    req = GLTGSimulationRequestV2.model_validate(payload())
    resolved = resolve_evidence(req, GiraffeDBClient(BASE, "test-provider-secret"))
    assert req.trade_processing_factors.material.material_availability_status == "partial_stock"
    assert req.trade_processing_factors.material.stock_coverage_ratio == .25
    assert req.trade_processing_factors.supplier_execution.supplier_execution_mode == "in_house_manufacturer"
    assert req.trade_processing_factors.processing.sample_days == 2
    assert req.behavior_features.supplier_snapshot_id == "snapshot-1"
    assert set(req.source_observation_ids) == {"snapshot-1", "obs-1"}
    assert resolved.explanation["evidence"]["factor_snapshot_id"] == "snapshot-1"


@respx.mock
def test_explicit_caller_facts_are_not_overwritten_by_snapshot():
    setup_provider({"material_availability_status": "in_stock"})
    data = payload()
    data["trade_processing_factors"] = {"material": {"material_availability_status": "not_available"}}
    req = GLTGSimulationRequestV2.model_validate(data)
    resolve_evidence(req, GiraffeDBClient(BASE, "test-provider-secret"))
    assert req.trade_processing_factors.material.material_availability_status == "not_available"


@respx.mock
def test_malformed_provider_factor_fails_closed(monkeypatch):
    setup_provider({"stock_coverage_ratio": -3})
    monkeypatch.setenv("GLTG_GIRAFFE_DB_BASE_URL", BASE)
    monkeypatch.setenv("GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET", "test-provider-secret")
    response = TestClient(app).post("/v2/lead-time/simulate", json=payload())
    assert response.status_code == 502
    assert response.json()["code"] == "EVIDENCE_MALFORMED"


@respx.mock
@pytest.mark.parametrize("readback", ["match", "wrong_tenant", "wrong_numbers", "unavailable"])
def test_persistence_checks_actual_case_api_readback(monkeypatch, readback):
    setup_provider({})
    monkeypatch.setenv("GLTG_GIRAFFE_DB_BASE_URL", BASE)
    monkeypatch.setenv("GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET", "test-provider-secret")
    monkeypatch.setenv("GLTG_PERSIST_RUNS", "true")
    stored = {}

    def save(request):
        import json
        stored.update(json.loads(request.content))
        stored.update(tenant_id=TENANT, gltg_run_id="run-1")
        return httpx.Response(200, json=stored)

    respx.post(f"{BASE}/api/data/gltg-simulation-runs").mock(side_effect=save)

    def get_graph(request):
        if readback == "unavailable":
            raise httpx.ReadTimeout("provider body must not escape")
        row = {**stored}
        if readback == "wrong_tenant":
            row["tenant_id"] = "other-tenant"
        if readback == "wrong_numbers":
            row["final_p50_days"] = -99
        return httpx.Response(200, json={"procurement_case": {"tenant_id": TENANT}, "gltg_runs": [row]})

    route = respx.get(f"{BASE}/api/data/procurement-cases/case-1/transaction-graph").mock(side_effect=get_graph)
    response = TestClient(app).post("/v2/lead-time/simulate", json=payload())
    assert response.status_code == 200
    persistence = response.json()["persistence"]
    assert route.call_count == 1
    if readback == "match":
        assert persistence["status"] == "persisted"
        assert persistence["readback_status"] == "verified"
    else:
        assert persistence["status"] == "indeterminate"
        assert persistence["persisted_to_giraffe_db"] is False
        assert persistence["giraffe_db_run_id"] == "run-1"
        assert "INDETERMINATE_COMMIT" in persistence["detail"]


@respx.mock
def test_post_timeout_is_unknown_write_outcome(monkeypatch):
    setup_provider({})
    monkeypatch.setenv("GLTG_GIRAFFE_DB_BASE_URL", BASE)
    monkeypatch.setenv("GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET", "test-provider-secret")
    monkeypatch.setenv("GLTG_PERSIST_RUNS", "true")
    respx.post(f"{BASE}/api/data/gltg-simulation-runs").mock(
        side_effect=httpx.ReadTimeout("raw private response"))
    result = TestClient(app).post("/v2/lead-time/simulate", json=payload()).json()
    assert result["persistence"]["status"] == "indeterminate"
    assert "INDETERMINATE_COMMIT" in result["persistence"]["detail"]
    assert "raw private" not in str(result)
