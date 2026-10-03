from __future__ import annotations

from gltg.behavioral.schemas import GLTGSimulationRequestV2
from gltg.behavioral.simulator import BehavioralLeadTimeSimulator


def test_trade_processing_p50_is_exact_component_sum_and_preserves_fraction() -> None:
    request = GLTGSimulationRequestV2.model_validate(
        {
            "request_id": "FORMULA-1",
            "tenant_id": "tenant-a",
            "order": {"quantity": 100},
            "supplier": {"capacity_per_day": 100},
            "trade_processing_factors": {
                "requirement": {"requirement_completeness_score": 1.0},
                "supplier_execution": {
                    "nominal_daily_capacity": 100,
                    "capacity_utilization_ratio": 0.5,
                    "priority_factor": 1.0,
                },
                "material": {
                    "material_availability_status": "in_stock",
                    "material_availability_confidence": 1.0,
                },
                "processing": {
                    "setup_days": 2.0,
                    "sample_required": True,
                    "sample_days": 3.0,
                    "color_approval_required": True,
                    "color_approval_days": 4.0,
                    "subprocess_days": 5.0,
                    "expected_yield_rate": 1.0,
                    "rework_probability": 0.0,
                },
                "logistics_trade": {
                    "route_baseline_days": 10.0,
                    "departure_frequency_days": 7.0,
                    "export_doc_readiness_score": 1.0,
                    "origin_inland_days": 1.0,
                    "import_clearance_days": 2.0,
                    "destination_inland_days": 2.0,
                },
            },
        }
    )

    result = BehavioralLeadTimeSimulator().simulate(request)
    components = result.components
    expected = sum(
        (
            components.requirement_confirmation_days,
            components.material_confirmation_days,
            components.material_procurement_days,
            components.preproduction_days,
            components.capacity_queue_days,
            components.production_days,
            components.qc_days,
            components.expected_rework_days,
            components.packaging_days,
            components.logistics_buffer_days,
            components.buyer_decision_buffer_days,
        )
    )

    assert components.preproduction_days == 7.0
    assert components.production_days == 10.0
    assert result.quantiles.p50_days == expected
    assert not result.quantiles.p50_days.is_integer()
    assert result.quantiles.p50_days < result.quantiles.p80_days < result.quantiles.p90_days


def test_material_confirmation_delay_is_included_in_p50() -> None:
    request = GLTGSimulationRequestV2.model_validate(
        {
            "request_id": "FORMULA-MATERIAL-CONFIRMATION",
            "tenant_id": "tenant-a",
            "order": {"quantity": 100},
            "supplier": {"capacity_per_day": 100},
            "trade_processing_factors": {
                "requirement": {"requirement_completeness_score": 1.0},
                "supplier_execution": {
                    "nominal_daily_capacity": 100,
                    "capacity_utilization_ratio": 0.5,
                    "priority_factor": 1.0,
                },
                "material": {
                    "material_availability_status": "not_available",
                    "material_availability_confidence": 0.0,
                    "procurement_baseline_days": 5.0,
                },
                "processing": {"expected_yield_rate": 1.0, "rework_probability": 0.0},
                "logistics_trade": {"export_doc_readiness_score": 1.0},
            },
        }
    )

    result = BehavioralLeadTimeSimulator().simulate(request)
    components = result.components
    expected = sum(
        (
            components.requirement_confirmation_days,
            components.material_confirmation_days,
            components.material_procurement_days,
            components.preproduction_days,
            components.capacity_queue_days,
            components.production_days,
            components.qc_days,
            components.expected_rework_days,
            components.packaging_days,
            components.logistics_buffer_days,
            components.buyer_decision_buffer_days,
        )
    )

    assert components.material_confirmation_days > 0
    assert result.quantiles.p50_days == expected
