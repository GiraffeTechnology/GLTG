"""Deterministic input-prep helpers shared by the engine adapter.

These normalize the HTTP transport DTOs before they are mapped onto the graph
engine: capacity-floor production, requirement-level baseline synthesis (incl.
destination/air-sea transit), the effective deadline, the evaluation anchor, and
additive reforecast deltas. They were the only still-used parts of the retired
summed-stage service layer.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from ..api.schemas import OrderInput, ReforecastEvent, SupplierInput
from .baselines import baseline_stage_days


def anchor_date(order: OrderInput) -> date:
    """Deterministic date math anchor; defaults to today at the HTTP boundary."""
    return order.evaluation_date or date.today()


def effective_target(order: OrderInput, anchor: date) -> date | None:
    """The deadline feasibility is measured against.

    Prefers an explicit ``target_delivery_date``; otherwise derives one from
    ``deadline_days`` so it is never silently ignored.
    """
    if order.target_delivery_date is not None:
        return order.target_delivery_date
    if order.deadline_days is not None:
        return anchor + timedelta(days=int(order.deadline_days))
    return None


def capacity_adjusted_production_days(supplier: SupplierInput, quantity: int) -> float:
    """Stated production days, raised to the capacity floor ceil(qty/capacity)."""
    stated = supplier.production_days
    if supplier.capacity_per_day and supplier.capacity_per_day > 0 and quantity > 0:
        capacity_floor = math.ceil(quantity / supplier.capacity_per_day)
        return float(max(stated, capacity_floor))
    return float(stated)


def maybe_apply_baselines(supplier: SupplierInput, order: OrderInput) -> SupplierInput:
    """Fill stage durations from GLTG baselines when a supplier provides none.

    A supplier with all stage days at 0 is treated as requirement-level input;
    GLTG synthesizes the stages so consumers never compute them locally.
    """
    has_stage_data = any(
        v > 0
        for v in (
            supplier.material_ready_days,
            supplier.production_days,
            supplier.qc_days,
            supplier.logistics_days,
        )
    )
    if has_stage_data:
        return supplier
    stages = baseline_stage_days(
        order.quantity, order.destination, order.logistics_mode, supplier.capacity_per_day
    )
    return supplier.model_copy(update=stages)


def apply_events(
    suppliers: list[SupplierInput], events: list[ReforecastEvent]
) -> tuple[list[SupplierInput], list[dict]]:
    """Apply additive per-stage deltas to deep copies (history never mutated)."""
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
    updated = [by_id[s.supplier_id] for s in suppliers]
    return updated, applied
