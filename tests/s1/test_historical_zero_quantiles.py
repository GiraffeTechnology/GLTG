"""Contract diagnostics for complete historical quantile triples containing zero."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gltg.behavioral.schemas import GLTGSimulationRequestV2
from gltg.behavioral.simulator import BehavioralLeadTimeSimulator


def _request(
    request_id: str,
    historical_baseline: dict[str, object],
) -> GLTGSimulationRequestV2:
    return GLTGSimulationRequestV2.model_validate(
        {
            "request_id": request_id,
            "tenant_id": "tenant-a",
            "order": {
                "product_type": "t-shirt",
                "quantity": 10_000,
                "deadline_days": 120,
            },
            "supplier": {
                "supplier_id": "GDB_SYN_V1_SUP_000001",
                "capacity_per_day": 800,
                "material_ready_days": 7,
                "production_days": 14,
                "qc_days": 3,
                "logistics_days": 20,
                "confidence": 0.8,
            },
            "historical_baseline": historical_baseline,
            "source_observation_ids": ["GDB_SYN_V1_OBS_000001"],
        }
    )


def _history(**overrides: object) -> dict[str, object]:
    baseline: dict[str, object] = {
        "baseline_source": "fixture_history",
        "sample_size": 10,
        "baseline_p50_days": 10,
        "baseline_p80_days": 20,
        "baseline_p90_days": 30,
    }
    baseline.update(overrides)
    return baseline


def _assert_ordered_nonnegative(response: object) -> None:
    quantiles = response.quantiles
    assert 0 <= quantiles.p50_days <= quantiles.p80_days <= quantiles.p90_days


def test_complete_historical_triple_with_zero_p50_is_not_treated_as_missing() -> None:
    request = _request("HIST-ZERO-P50", _history(baseline_p50_days=0))

    response = BehavioralLeadTimeSimulator().simulate(request)

    assert response.explanation_json["baseline_source"] == "fixture_history"
    _assert_ordered_nonnegative(response)


def test_complete_all_zero_historical_triple_is_not_treated_as_missing() -> None:
    request = _request(
        "HIST-ALL-ZERO",
        _history(baseline_p50_days=0, baseline_p80_days=0, baseline_p90_days=0),
    )

    response = BehavioralLeadTimeSimulator().simulate(request)

    assert response.explanation_json["baseline_source"] == "fixture_history"
    _assert_ordered_nonnegative(response)


def test_complete_positive_historical_triple_remains_primary() -> None:
    request = _request("HIST-POSITIVE", _history())

    response = BehavioralLeadTimeSimulator().simulate(request)

    assert response.explanation_json["baseline_source"] == "fixture_history"
    _assert_ordered_nonnegative(response)


def test_null_member_is_incomplete_and_uses_requirement_baseline() -> None:
    request = _request("HIST-NULL", _history(baseline_p50_days=None))

    response = BehavioralLeadTimeSimulator().simulate(request)

    assert response.explanation_json["baseline_source"] == "gltg_requirement_baseline"
    _assert_ordered_nonnegative(response)


def test_negative_historical_quantile_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _request("HIST-NEGATIVE", _history(baseline_p50_days=-0.01))
