"""Stage 3 required invariants for the deterministic v2 engine (default mode)."""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from gltg.api.main import app
from gltg.behavioral.schemas import GLTGOrderInputV2, GLTGSimulationRequestV2
from gltg.behavioral.simulator import BehavioralLeadTimeSimulator

client = TestClient(app)
_simulator = BehavioralLeadTimeSimulator()


def _request(**overrides) -> GLTGSimulationRequestV2:
    base = {
        "request_id": "INV-1",
        "tenant_id": "tenant-a",
        "order": {"product_type": "t-shirt", "quantity": 10000, "deadline_days": 120},
        "supplier": {
            "supplier_id": "GDB_SYN_V1_SUP_000001",
            "capacity_per_day": 800,
            "material_ready_days": 7,
            "production_days": 14,
            "qc_days": 3,
            "logistics_days": 20,
            "confidence": 0.8,
        },
        "source_observation_ids": ["GDB_SYN_V1_OBS_000001"],
    }
    base.update(overrides)
    return GLTGSimulationRequestV2.model_validate(base)


CASES = [
    _request(),
    _request(request_id="INV-2", historical_baseline={
        "baseline_p50_days": 40, "baseline_p80_days": 52, "baseline_p90_days": 60,
    }),
    _request(request_id="INV-3", behavior_features={
        "supplier": {"response_delay_ratio": 3.4, "quote_completeness_score": 0.4},
        "buyer": {"buyer_decision_delay_score": 0.9, "requirement_change_count": 3},
    }),
    _request(request_id="INV-4", trade_processing_factors={
        "material": {"material_availability_status": "unknown"},
        "supplier_execution": {"capacity_utilization_ratio": 0.95, "supplier_execution_mode": "trader"},
        "logistics_trade": {"freight_space_risk": 0.8},
    }),
    _request(request_id="INV-5", order={"product_type": "t-shirt", "quantity": 1, "deadline_days": 1}),
]


@pytest.mark.parametrize("req", CASES, ids=[c.request_id for c in CASES])
def test_quantile_monotonicity_and_nonnegative_days(req):
    res = _simulator.simulate(copy.deepcopy(req))
    q = res.quantiles
    assert 0 <= q.p50_days <= q.p80_days <= q.p90_days
    for name, value in res.components.model_dump().items():
        assert value >= 0, f"negative component {name}={value}"


@pytest.mark.parametrize("req", CASES, ids=[c.request_id for c in CASES])
def test_confidence_bounds(req):
    res = _simulator.simulate(copy.deepcopy(req))
    assert 0.0 <= res.risk.confidence_score <= 1.0


@pytest.mark.parametrize("req", CASES, ids=[c.request_id for c in CASES])
def test_determinism_same_input_same_output(req):
    first = _simulator.simulate(copy.deepcopy(req)).model_dump(mode="json")
    second = _simulator.simulate(copy.deepcopy(req)).model_dump(mode="json")
    assert first == second


def test_v2_http_determinism_repeated_calls():
    payload = _request().model_dump(mode="json")
    bodies = [client.post("/v2/lead-time/simulate", json=payload).json() for _ in range(3)]
    assert bodies[0] == bodies[1] == bodies[2]
    assert bodies[0]["gltg_run_id"].startswith("GLTG_")


def test_deadline_feasibility_matches_selected_quantile():
    req = _request(request_id="INV-DL", constraints={"lead_time_confidence": "P90"})
    res = _simulator.simulate(req)
    assert res.risk.selected_confidence_days == res.quantiles.p90_days
    assert res.risk.deadline_feasible == (res.quantiles.p90_days <= 120)


def test_missing_data_is_disclosed():
    req = _request(request_id="INV-MISS", source_observation_ids=[])
    res = _simulator.simulate(req)
    assert any(w.code == "MISSING_SOURCE_OBSERVATIONS" for w in res.warnings)
    assert res.source_observation_ids == []


def test_no_supplier_or_source_ids_invented():
    req = _request(request_id="INV-IDS")
    res = _simulator.simulate(req)
    assert set(res.source_observation_ids) <= set(req.source_observation_ids)
    # fallback supplier is a boolean recommendation, never an invented ID
    assert not hasattr(res.risk, "fallback_supplier_id")


def test_manual_review_is_explainable():
    req = _request(request_id="INV-MR", behavior_features={
        "supplier": {"quote_completeness_score": 0.2},
    })
    res = _simulator.simulate(req)
    assert res.risk.manual_review_required is True
    assert any(w.code == "QUOTE_INCOMPLETE" for w in res.warnings)
    assert any(
        adj["feature"] == "quote_completeness_score"
        for adj in res.explanation_json["adjustments"]
    )


def test_increasing_production_days_never_reduces_quantiles():
    previous = None
    for production_days in (5, 10, 20, 40, 80):
        req = _request(request_id=f"INV-MONO-{production_days}")
        req.supplier.production_days = production_days
        res = _simulator.simulate(req)
        if previous is not None:
            assert res.quantiles.p50_days >= previous.p50_days
            assert res.quantiles.p80_days >= previous.p80_days
            assert res.quantiles.p90_days >= previous.p90_days
        previous = res.quantiles


def test_increasing_logistics_days_never_reduces_quantiles():
    previous = None
    for logistics_days in (5, 15, 30, 45):
        req = _request(request_id=f"INV-LOG-{logistics_days}")
        req.supplier.logistics_days = logistics_days
        res = _simulator.simulate(req)
        if previous is not None:
            assert res.quantiles.p90_days >= previous.p90_days
        previous = res.quantiles


def test_worse_delay_never_improves():
    previous = None
    for ratio in (1.0, 1.5, 2.5, 3.5, 6.0):
        req = _request(request_id=f"INV-DELAY-{ratio}")
        req.behavior_features.supplier.response_delay_ratio = ratio
        res = _simulator.simulate(req)
        if previous is not None:
            assert res.quantiles.p50_days >= previous.p50_days
            assert res.quantiles.p90_days >= previous.p90_days
        previous = res.quantiles


def test_more_uncertainty_never_narrows():
    req_low = _request(request_id="INV-U-low", historical_baseline={
        "baseline_p50_days": 40, "baseline_p80_days": 44, "baseline_p90_days": 48,
    })
    req_high = _request(request_id="INV-U-low", historical_baseline={
        "baseline_p50_days": 40, "baseline_p80_days": 44, "baseline_p90_days": 48,
    })
    req_high.behavior_features.supplier.quote_completeness_score = 0.3
    low = _simulator.simulate(req_low).quantiles
    high = _simulator.simulate(req_high).quantiles
    assert (high.p90_days - high.p50_days) >= (low.p90_days - low.p50_days)


def test_removing_evidence_never_raises_confidence():
    with_evidence = _request(request_id="INV-EV")
    without_evidence = _request(request_id="INV-EV", source_observation_ids=[])
    conf_with = _simulator.simulate(with_evidence).risk.confidence_score
    conf_without = _simulator.simulate(without_evidence).risk.confidence_score
    assert conf_without <= conf_with


def test_removing_baseline_sample_never_raises_confidence():
    small = _request(request_id="INV-BASE", historical_baseline={
        "baseline_p50_days": 40, "baseline_p80_days": 52, "baseline_p90_days": 60,
        "sample_size": 5,
    })
    large = _request(request_id="INV-BASE", historical_baseline={
        "baseline_p50_days": 40, "baseline_p80_days": 52, "baseline_p90_days": 60,
        "sample_size": 60,
    })
    assert (
        _simulator.simulate(small).risk.confidence_score
        <= _simulator.simulate(large).risk.confidence_score
    )


# ------------------------------------------------------------------ #
# 0 / 1 / 2 / 3+ supplier behavior (v1 comparison surface + v2 paths)
# ------------------------------------------------------------------ #
def _v1_payload(supplier_count: int) -> dict:
    suppliers = [
        {
            "supplier_id": f"S{i}",
            "capacity_per_day": 800,
            "material_ready_days": 5,
            "production_days": 14,
            "qc_days": 2,
            "logistics_days": 7,
            "confidence": 0.8,
        }
        for i in range(supplier_count)
    ]
    return {
        "order": {"product_type": "apparel", "quantity": 1000, "deadline_days": 300},
        "suppliers": suppliers,
    }


def test_zero_suppliers_never_crashes():
    body = client.post("/v1/lead-time/estimate", json=_v1_payload(0)).json()
    assert body["feasible"] is False
    assert any(w["code"] == "NO_SUPPLIERS" for w in body["warnings"])


def test_one_supplier_limited_comparison_warning():
    body = client.post("/v1/lead-time/estimate", json=_v1_payload(1)).json()
    assert any(w["code"] == "LIMITED_COMPARISON" for w in body["warnings"])


def test_two_suppliers_limited_pool_warning():
    body = client.post("/v1/lead-time/estimate", json=_v1_payload(2)).json()
    assert any(w["code"] == "LIMITED_SUPPLIER_POOL" for w in body["warnings"])


def test_three_plus_suppliers_normal_comparison():
    body = client.post("/v1/lead-time/estimate", json=_v1_payload(3)).json()
    codes = {w["code"] for w in body["warnings"]}
    assert "LIMITED_COMPARISON" not in codes
    assert "LIMITED_SUPPLIER_POOL" not in codes
    assert body["supplier_count"] == 3


def test_v2_paths_zero_simulations_never_crashes():
    body = client.post("/v2/paths/enumerate", json={"simulations": []}).json()
    assert body["ok"] is True
    assert body["paths"] == []
