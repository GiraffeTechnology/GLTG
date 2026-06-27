"""Tests for the additive percentile bands, risk level, and baseline synthesis."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gltg.api.main import app

client = TestClient(app)


def test_estimate_returns_ordered_percentile_bands():
    payload = {
        "order": {"quantity": 10000, "evaluation_date": "2026-06-27"},
        "suppliers": [
            {
                "supplier_id": "M1",
                "capacity_per_day": 800,
                "material_ready_days": 5,
                "production_days": 14,
                "qc_days": 2,
                "logistics_days": 7,
                "confidence": 0.8,
            }
        ],
    }
    body = client.post("/v1/lead-time/estimate", json=payload).json()
    assert body["p50_days"] == 28
    assert body["p80_days"] >= body["p50_days"]
    assert body["p90_days"] >= body["p80_days"]
    assert body["minimum_feasible_days"] <= body["p50_days"]
    assert body["risk_level"] in {"low", "medium", "high", "unknown"}


def test_lower_confidence_widens_bands():
    base = {
        "supplier_id": "S",
        "capacity_per_day": 800,
        "material_ready_days": 5,
        "production_days": 14,
        "qc_days": 2,
        "logistics_days": 7,
    }
    hi = client.post(
        "/v1/lead-time/estimate",
        json={"order": {"quantity": 10000}, "suppliers": [{**base, "confidence": 0.95}]},
    ).json()
    lo = client.post(
        "/v1/lead-time/estimate",
        json={"order": {"quantity": 10000}, "suppliers": [{**base, "confidence": 0.2}]},
    ).json()
    # Same median, but lower confidence pushes p90 out further.
    assert lo["p90_days"] >= hi["p90_days"]


def test_baseline_synthesis_for_requirement_level_supplier():
    # Supplier with no stage data -> GLTG fills baselines from quantity + destination.
    payload = {
        "order": {"quantity": 1000, "destination": "Los Angeles", "logistics_mode": "sea"},
        "suppliers": [{"supplier_id": "req"}],
    }
    body = client.post("/v1/lead-time/estimate", json=payload).json()
    assert body["estimated_lead_time_days"] > 0
    trace = body["calculation_trace"][0]
    assert trace["material_ready_days"] > 0
    assert trace["logistics_days"] > 0  # includes sea transit to LA


def test_air_logistics_faster_than_sea():
    sea = client.post(
        "/v1/lead-time/estimate",
        json={"order": {"quantity": 1000, "destination": "London", "logistics_mode": "sea"}, "suppliers": [{"supplier_id": "r"}]},
    ).json()
    air = client.post(
        "/v1/lead-time/estimate",
        json={"order": {"quantity": 1000, "destination": "London", "logistics_mode": "air"}, "suppliers": [{"supplier_id": "r"}]},
    ).json()
    assert air["estimated_lead_time_days"] < sea["estimated_lead_time_days"]
