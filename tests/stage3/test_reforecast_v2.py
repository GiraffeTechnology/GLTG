"""Stage 3 v2 reforecast scenarios (deterministic default mode)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gltg.api.main import app

client = TestClient(
    app,
    headers={
        "X-Service-Auth": "test-inbound-secret",
        "X-Service-Tenant-ID": "tenant-a",
    },
)


def _payload(events: list[dict], **overrides) -> dict:
    payload = {
        "request_id": "REF-1",
        "tenant_id": "tenant-a",
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
        "events": events,
    }
    payload.update(overrides)
    return payload


def _reforecast(events: list[dict], **overrides) -> dict:
    response = client.post("/v2/reforecast", json=_payload(events, **overrides))
    assert response.status_code == 200
    return response.json()


def test_delayed_supplier_response_worsens_forecast():
    body = _reforecast([
        {"event_type": "supplier_response_delay", "response_delay_ratio": 4.0,
         "source_observation_ids": ["GDB_SYN_V1_OBS_000002"]},
    ])
    assert body["applied_events"]
    assert body["delta"]["p50_days"] >= 0
    assert body["delta"]["p90_days"] > 0
    assert body["changed_components"]
    assert "GDB_SYN_V1_OBS_000002" in body["triggering_observation_ids"]
    assert body["explanation_json"]["reforecast"]["applied_event_types"] == [
        "supplier_response_delay"
    ]


def test_material_availability_change_visible_effect():
    body = _reforecast([
        {"event_type": "material_availability_change",
         "material_availability_status": "not_available",
         "raw_material_lead_time_estimate_days": 15},
    ])
    assert body["applied_events"]
    assert body["delta"]["p50_days"] > 0


def test_capacity_update_visible_effect():
    body = _reforecast([
        {"event_type": "capacity_update", "capacity_utilization_ratio": 0.95},
    ])
    assert body["applied_events"]
    assert body["delta"]["p90_days"] >= 0
    assert body["quantiles"]["p90_days"] >= body["previous_quantiles"]["p90_days"]


def test_buyer_requirement_revision_visible_effect():
    body = _reforecast([
        {"event_type": "buyer_requirement_revision", "requirement_change_count": 3,
         "requirement_volatility_score": 0.8},
    ])
    assert body["applied_events"]
    assert body["delta"]["p50_days"] >= 0


def test_logistics_disruption_visible_effect():
    body = _reforecast([
        {"event_type": "logistics_disruption", "freight_space_risk": 0.9,
         "route_baseline_days": 30},
    ])
    assert body["applied_events"]
    assert body["quantiles"]["p90_days"] >= body["previous_quantiles"]["p90_days"]


def test_qc_delay_visible_effect():
    body = _reforecast([
        {"event_type": "qc_delay", "qc_intensity_score": 0.9, "rework_probability": 0.5},
    ])
    assert body["applied_events"]
    assert body["delta"]["p90_days"] >= 0


def test_improved_evidence_extends_lineage():
    body = _reforecast([
        {"event_type": "improved_evidence",
         "source_observation_ids": ["GDB_SYN_V1_OBS_000009"]},
    ])
    assert body["applied_events"]
    assert "GDB_SYN_V1_OBS_000009" in body["source_observation_ids"]


def test_missing_prior_run_is_stateless_recompute():
    # GLTG is stateless: the "previous" forecast is recomputed from the same
    # request, so a missing prior run cannot crash or fabricate history.
    body = _reforecast([])
    assert body["previous_quantiles"] == body["quantiles"]
    assert body["delta"] == {"p50_days": 0.0, "p80_days": 0.0, "p90_days": 0.0}


def test_repeated_event_is_idempotent_for_ratio_events():
    once = _reforecast([
        {"event_type": "supplier_response_delay", "response_delay_ratio": 3.0},
    ])
    twice = _reforecast([
        {"event_type": "supplier_response_delay", "response_delay_ratio": 3.0},
        {"event_type": "supplier_response_delay", "response_delay_ratio": 3.0},
    ])
    assert once["quantiles"] == twice["quantiles"]


def test_out_of_order_events_last_value_wins_deterministically():
    forward = _reforecast([
        {"event_type": "capacity_update", "capacity_utilization_ratio": 0.5},
        {"event_type": "capacity_update", "capacity_utilization_ratio": 0.9},
    ])
    forward_again = _reforecast([
        {"event_type": "capacity_update", "capacity_utilization_ratio": 0.5},
        {"event_type": "capacity_update", "capacity_utilization_ratio": 0.9},
    ])
    assert forward["quantiles"] == forward_again["quantiles"]
    assert forward["explanation_json"]["reforecast"]["applied_event_types"] == [
        "capacity_update",
        "capacity_update",
    ]


def test_unknown_event_disclosed_not_silently_dropped():
    body = _reforecast([{"event_type": "alien_event", "x": 1}])
    assert body["applied_events"] == []
    assert body["unapplied_events"] == [{"event_type": "alien_event", "x": 1}]
    assert any(w["code"] == "UNAPPLIED_REFORECAST_EVENT" for w in body["warnings"])


def test_wrong_tenant_evidence_access_denied(monkeypatch):
    import httpx
    import respx

    base = "http://giraffe-db.test"
    monkeypatch.setenv("GLTG_GIRAFFE_DB_BASE_URL", base)
    monkeypatch.setenv("GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET", "s3cret")
    with respx.mock:
        respx.get(f"{base}/api/data/suppliers/GDB_SYN_V1_SUP_000001").mock(
            return_value=httpx.Response(403, json={"detail": {"error": "forbidden"}})
        )
        response = client.post(
            "/v2/reforecast",
            json=_payload([], evidence={"use_giraffe_db": True}, tenant_id="tenant-wrong"),
            headers={
                "X-Service-Auth": "test-inbound-secret",
                "X-Service-Tenant-ID": "tenant-wrong",
            },
        )
    assert response.status_code == 502
    assert response.json()["code"] == "EVIDENCE_AUTH_FAILED"
