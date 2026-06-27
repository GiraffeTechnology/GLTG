"""HTTP API tests for the GLTG service (health, version, v1 endpoints)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gltg.api.main import app
from gltg.version import __version__

client = TestClient(app)


def _supplier(sid: str, **over) -> dict:
    base = {
        "supplier_id": sid,
        "name": f"Supplier {sid}",
        "capacity_per_day": 800,
        "material_ready_days": 5,
        "production_days": 14,
        "qc_days": 2,
        "logistics_days": 7,
        "confidence": 0.8,
    }
    base.update(over)
    return base


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "gltg"}


def test_version():
    r = client.get("/version")
    assert r.status_code == 200
    body = r.json()
    assert body == {"service": "gltg", "version": __version__, "api_version": "v1"}


def test_estimate_matches_spec_example():
    # DEFECT-01: estimate is now engine-derived (full 22-node apparel workflow:
    # fabric ordering, sampling, customs, sea freight, rework buffer), not the old
    # 4-stage sum. The supplier's 4 stages are injected onto the dominant nodes;
    # the rest fall to category baselines.
    payload = {
        "order": {
            "product_type": "apparel",
            "quantity": 10000,
            "target_delivery_date": "2026-12-31",
            "evaluation_date": "2026-06-27",
        },
        "suppliers": [_supplier("M1")],
        "constraints": {"allow_partial_suppliers": True, "min_supplier_count": 0, "currency": "USD"},
    }
    r = client.post("/v1/lead-time/estimate", json=payload)
    assert r.status_code == 200
    body = r.json()
    # updated: was service-layer sum=28, now engine commitable=147
    assert body["estimated_lead_time_days"] == 147
    assert body["feasible"] is True
    assert body["supplier_count"] == 1
    assert body["selected_supplier_id"] == "M1"
    # updated: was 2026-07-25 (anchor+28); now engine earliest_feasible=2026-09-09
    assert body["earliest_delivery_date"] == "2026-09-09"
    # additive engine fields are populated (DEFECT-01). feasibility mirrors the
    # engine FeasibilityStatus: a single option triggers the 0/1/2/3 rule ->
    # LIMITED_OPTIONS (distinct from the `feasible` deadline boolean above).
    assert body["committable_date"] == "2026-11-21"
    assert body["feasibility"] == "LIMITED_OPTIONS"
    assert any(w["code"] == "LIMITED_COMPARISON" for w in body["warnings"])
    assert len(body["calculation_trace"]) == 1


def test_capacity_floor_raises_production():
    # capacity 100/day for 10000 -> floor 100 days > stated 14
    payload = {
        "order": {"quantity": 10000, "evaluation_date": "2026-06-27"},
        "suppliers": [_supplier("S", capacity_per_day=100)],
    }
    r = client.post("/v1/lead-time/estimate", json=payload)
    trace = r.json()["calculation_trace"][0]
    # Capacity floor is preserved as engine input-prep: production raised to 100.
    assert trace["capacity_adjusted_production_days"] == 100
    # updated: was service-layer sum 5+100+2+7=114, now engine commitable=284
    # (the capacity-raised production still dominates the engine result).
    assert r.json()["estimated_lead_time_days"] == 284


def test_zero_suppliers():
    payload = {"order": {"quantity": 1000}, "suppliers": []}
    r = client.post("/v1/lead-time/estimate", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["feasible"] is False
    assert body["supplier_count"] == 0
    assert body["estimated_lead_time_days"] is None
    assert any(w["code"] == "NO_SUPPLIERS" for w in body["warnings"])


def test_one_supplier_warns_limited_comparison():
    payload = {"order": {"quantity": 1000}, "suppliers": [_supplier("A")]}
    body = client.post("/v1/lead-time/estimate", json=payload).json()
    assert body["supplier_count"] == 1
    assert any(w["code"] == "LIMITED_COMPARISON" for w in body["warnings"])


def test_two_suppliers_warns_limited_pool():
    payload = {"order": {"quantity": 1000}, "suppliers": [_supplier("A"), _supplier("B")]}
    body = client.post("/v1/lead-time/estimate", json=payload).json()
    assert body["supplier_count"] == 2
    assert any(w["code"] == "LIMITED_SUPPLIER_POOL" for w in body["warnings"])


def test_three_suppliers_no_pool_warning():
    payload = {
        "order": {"quantity": 1000},
        "suppliers": [_supplier("A"), _supplier("B"), _supplier("C")],
    }
    body = client.post("/v1/lead-time/estimate", json=payload).json()
    assert body["supplier_count"] == 3
    codes = {w["code"] for w in body["warnings"]}
    assert "LIMITED_COMPARISON" not in codes
    assert "LIMITED_SUPPLIER_POOL" not in codes


def test_selects_fastest_feasible_supplier():
    fast = _supplier("FAST", production_days=5)
    slow = _supplier("SLOW", production_days=30)
    payload = {"order": {"quantity": 1000}, "suppliers": [slow, fast]}
    body = client.post("/v1/lead-time/estimate", json=payload).json()
    assert body["selected_supplier_id"] == "FAST"


def test_paths_enumerate_deterministic_ranking():
    payload = {
        "order": {"quantity": 10000},
        "suppliers": [_supplier("A", production_days=20), _supplier("B", production_days=10)],
    }
    body = client.post("/v1/paths/enumerate", json=payload).json()
    assert body["supplier_count"] == 2
    # single A, single B, plus parallel split = 3 paths
    assert len(body["paths"]) == 3
    ranks = [p["rank"] for p in body["paths"]]
    assert ranks == [1, 2, 3]
    # ranking is deterministic & stable across calls
    body2 = client.post("/v1/paths/enumerate", json=payload).json()
    assert [p["path_id"] for p in body["paths"]] == [p["path_id"] for p in body2["paths"]]
    assert any(p["mode"] == "PARALLEL_SPLIT" for p in body["paths"])


def test_paths_zero_suppliers():
    body = client.post("/v1/paths/enumerate", json={"order": {"quantity": 100}, "suppliers": []}).json()
    assert body["paths"] == []
    assert any(w["code"] == "NO_SUPPLIERS" for w in body["warnings"])


def test_reforecast_applies_delta_without_mutating_baseline():
    suppliers = [_supplier("M1")]
    payload = {
        "order": {"quantity": 10000, "evaluation_date": "2026-06-27"},
        "suppliers": suppliers,
        "events": [{"supplier_id": "M1", "production_days_delta": 6, "note": "machine breakdown"}],
    }
    body = client.post("/v1/reforecast", json=payload).json()
    # updated: was service-layer sums 28 -> 34 (delta 6). Now engine-derived:
    # the +6 production delta is blended through the SEWING node, so the engine
    # commitable shifts 147 -> 157 (delta 10).
    assert body["baseline_lead_time_days"] == 147
    assert body["updated_lead_time_days"] == 157
    assert body["delta_days"] == 10
    assert body["applied_events"][0]["applied"] is True


def test_reforecast_unknown_supplier_event():
    payload = {
        "order": {"quantity": 1000},
        "suppliers": [_supplier("M1")],
        "events": [{"supplier_id": "GHOST", "production_days_delta": 3}],
    }
    body = client.post("/v1/reforecast", json=payload).json()
    assert body["applied_events"][0]["applied"] is False
    assert body["applied_events"][0]["reason"] == "unknown_supplier"
