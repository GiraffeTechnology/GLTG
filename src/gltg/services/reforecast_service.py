"""Deterministic reforecasting service.

Applies updated supplier/order/logistics facts (as additive per-stage deltas)
on top of the baseline and returns an updated lead-time forecast. The original
supplier inputs are never mutated -- deltas are applied to deep copies so the
historical baseline remains intact and auditable.
"""

from __future__ import annotations

from ..api.schemas import (
    Constraints,
    LeadTimeEstimateResponse,
    OrderInput,
    ReforecastEvent,
    ReforecastResponse,
    SupplierInput,
)
from .lead_time_service import estimate


def _apply_events(
    suppliers: list[SupplierInput], events: list[ReforecastEvent]
) -> tuple[list[SupplierInput], list[dict]]:
    """Return updated supplier copies plus an audit list of applied events.

    Inputs are copied (model_copy) so historical baseline data is never mutated.
    """
    by_id = {s.supplier_id: s.model_copy(deep=True) for s in suppliers}
    applied: list[dict] = []
    for ev in events:
        target = by_id.get(ev.supplier_id)
        if target is None:
            applied.append(
                {"supplier_id": ev.supplier_id, "applied": False, "reason": "unknown_supplier"}
            )
            continue
        target.material_ready_days = max(0.0, target.material_ready_days + ev.material_ready_days_delta)
        target.production_days = max(0.0, target.production_days + ev.production_days_delta)
        target.qc_days = max(0.0, target.qc_days + ev.qc_days_delta)
        target.logistics_days = max(0.0, target.logistics_days + ev.logistics_days_delta)
        applied.append(
            {
                "supplier_id": ev.supplier_id,
                "applied": True,
                "material_ready_days_delta": ev.material_ready_days_delta,
                "production_days_delta": ev.production_days_delta,
                "qc_days_delta": ev.qc_days_delta,
                "logistics_days_delta": ev.logistics_days_delta,
                "note": ev.note,
            }
        )
    # Preserve original ordering.
    updated = [by_id[s.supplier_id] for s in suppliers]
    return updated, applied


def reforecast(
    order: OrderInput,
    suppliers: list[SupplierInput],
    events: list[ReforecastEvent],
    constraints: Constraints,
) -> ReforecastResponse:
    baseline: LeadTimeEstimateResponse = estimate(order, suppliers, constraints)
    updated_suppliers, applied = _apply_events(suppliers, events)
    updated: LeadTimeEstimateResponse = estimate(order, updated_suppliers, constraints)

    delta = None
    if baseline.estimated_lead_time_days is not None and updated.estimated_lead_time_days is not None:
        delta = round(updated.estimated_lead_time_days - baseline.estimated_lead_time_days, 4)

    return ReforecastResponse(
        status="ok",
        baseline_lead_time_days=baseline.estimated_lead_time_days,
        updated_lead_time_days=updated.estimated_lead_time_days,
        delta_days=delta,
        earliest_delivery_date=updated.earliest_delivery_date,
        feasible=updated.feasible,
        supplier_count=updated.supplier_count,
        selected_supplier_id=updated.selected_supplier_id,
        applied_events=applied,
        warnings=updated.warnings,
        calculation_trace=updated.calculation_trace,
    )
