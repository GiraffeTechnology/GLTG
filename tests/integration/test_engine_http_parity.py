"""DEFECT-01 parity: the HTTP layer must return the engine's result.

Definition of done for DEFECT-01 — for the selected supplier, the HTTP response
dates and lead time must equal what `LeadTimeGraphEngine.evaluate()` produces for
the same constructed order. This proves the HTTP path is engine-backed, not a
separate summed-stage calculator.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from gltg import LeadTimeGraphEngine
from gltg.api.main import app
from gltg.api.schemas import OrderInput, SupplierInput
from gltg.services.engine_adapter import _build_order_for_supplier

client = TestClient(app)
ENGINE = LeadTimeGraphEngine()

ANCHOR = "2026-06-27"


def _reference_payload() -> dict:
    return {
        "order": {
            "product_type": "apparel",
            "quantity": 10000,
            "target_delivery_date": "2026-12-31",
            "evaluation_date": ANCHOR,
        },
        "suppliers": [
            {"supplier_id": "A", "capacity_per_day": 800, "material_ready_days": 5,
             "production_days": 14, "qc_days": 2, "logistics_days": 7, "confidence": 0.8},
            {"supplier_id": "B", "capacity_per_day": 1200, "material_ready_days": 4,
             "production_days": 10, "qc_days": 2, "logistics_days": 6, "confidence": 0.7},
        ],
    }


def test_http_estimate_equals_direct_engine_for_selected_supplier():
    payload = _reference_payload()
    body = client.post("/v1/lead-time/estimate", json=payload).json()

    # Rebuild the engine order for the SELECTED supplier and evaluate directly.
    selected_id = body["selected_supplier_id"]
    selected = next(s for s in payload["suppliers"] if s["supplier_id"] == selected_id)
    anchor = date.fromisoformat(ANCHOR)
    order_input = _build_order_for_supplier(
        OrderInput(**payload["order"]), SupplierInput(**selected), anchor
    )
    packet = ENGINE.evaluate(order_input)

    commitable_lead = (packet.commitable_date - anchor).days
    assert body["estimated_lead_time_days"] == commitable_lead
    assert body["committable_date"] == packet.commitable_date.isoformat()
    assert body["most_likely_date"] == packet.most_likely_date.isoformat()
    assert body["risk_adjusted_date"] == packet.risk_adjusted_latest_date.isoformat()
    assert body["earliest_delivery_date"] == packet.earliest_feasible_date.isoformat()
    assert body["feasibility"] == packet.status.value


def test_http_estimate_is_not_the_legacy_stage_sum():
    """Guard against silent regression to the summed-stage calculator."""
    payload = _reference_payload()
    body = client.post("/v1/lead-time/estimate", json=payload).json()
    selected = next(s for s in payload["suppliers"] if s["supplier_id"] == body["selected_supplier_id"])
    stage_sum = (selected["material_ready_days"] + selected["production_days"]
                 + selected["qc_days"] + selected["logistics_days"])
    # The engine accounts for the full workflow, so it must exceed the 4-stage sum.
    assert body["estimated_lead_time_days"] > stage_sum


def test_http_capacity_drives_supplier_selection():
    """DEFECT-03 over HTTP: with stage durations equal, the higher-capacity
    supplier wins because its SEWING node is shorter."""
    payload = {
        "order": {"quantity": 10000, "evaluation_date": ANCHOR},
        "suppliers": [
            {"supplier_id": "SLOW", "capacity_per_day": 200, "material_ready_days": 5,
             "production_days": 14, "qc_days": 2, "logistics_days": 7, "confidence": 0.8},
            {"supplier_id": "FAST", "capacity_per_day": 5000, "material_ready_days": 5,
             "production_days": 14, "qc_days": 2, "logistics_days": 7, "confidence": 0.8},
        ],
    }
    body = client.post("/v1/lead-time/estimate", json=payload).json()
    assert body["selected_supplier_id"] == "FAST"
    # The two suppliers' own engine lead times must differ by capacity.
    traces = {t["supplier_id"]: t["total_lead_time_days"] for t in body["calculation_trace"]}
    assert traces["SLOW"] > traces["FAST"]
