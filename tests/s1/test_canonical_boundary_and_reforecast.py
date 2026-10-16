import respx
from fastapi.testclient import TestClient

from gltg.api.main import app
from gltg.behavioral.schemas import GLTGSimulationRequestV2
from gltg.behavioral.simulator import BehavioralLeadTimeSimulator


def test_deadline_feasibility_uses_the_returned_canonical_precision(monkeypatch):
    engine = BehavioralLeadTimeSimulator()
    monkeypatch.setattr(engine, "_compose_trade_processing_spread", lambda *args: (10.000001, 20.000001, 30.000001))
    req = GLTGSimulationRequestV2.model_validate({
        "request_id": "CUTOFF", "tenant_id": "tenant-a", "order": {"quantity": 100, "deadline_days": 20},
        "trade_processing_factors": {"requirement": {"requirement_completeness_score": 1}}})
    response = engine.simulate(req)
    assert response.quantiles.p80_days == 20
    assert response.risk.selected_confidence_days == 20
    assert response.risk.deadline_feasible is True


def test_invalid_reforecast_factor_is_rejected_before_calculation():
    response = TestClient(app).post("/v2/reforecast", json={
        "request_id": "INVALID-EVENT", "tenant_id": "tenant-a", "order": {"quantity": 100},
        "events": [{"event_type": "logistics_disruption", "route_baseline_days": -20}]})
    assert response.status_code == 422


@respx.mock
def test_reforecast_event_cannot_smuggle_unowned_source_observations(monkeypatch):
    monkeypatch.setenv("GLTG_GIRAFFE_DB_BASE_URL", "http://provider.test")
    monkeypatch.setenv("GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET", "test-provider-secret")
    respx.get("http://provider.test/api/data/suppliers/supplier-1").respond(
        200, json={"tenant_id": "tenant-a", "supplier_id": "supplier-1"})
    respx.get("http://provider.test/api/data/suppliers/supplier-1/behavior-summary").respond(
        200, json={"tenant_id": "tenant-a", "supplier_id": "supplier-1", "observation_count": 0,
                   "latest_snapshot": None})
    response = TestClient(app).post("/v2/reforecast", json={
        "request_id": "EVENT-OWNER", "tenant_id": "tenant-a", "order": {"quantity": 100},
        "supplier": {"supplier_id": "supplier-1"}, "evidence": {"use_giraffe_db": True},
        "events": [{"event_type": "improved_evidence", "source_observation_ids": ["foreign-observation"]}]})
    assert response.status_code == 403
    assert response.json()["code"] == "EVIDENCE_REFERENCE_FORBIDDEN"
