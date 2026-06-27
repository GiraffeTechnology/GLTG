"""Deterministic lead-time estimation service.

This is the API-facing, deterministic lead-time logic. It is intentionally
free of any LLM/heuristic guessing: given the same inputs it always returns
the same output. It also never raises on small supplier pools -- the 0/1/2/3+
supplier edge cases are first-class results, not errors.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from ..api.schemas import (
    Constraints,
    LeadTimeEstimateResponse,
    OrderInput,
    SupplierInput,
    SupplierTrace,
    Warning,
)


def _capacity_adjusted_production_days(supplier: SupplierInput, quantity: int) -> float:
    """Production days, never shorter than capacity allows for the quantity.

    If a supplier states 14 production days but can only make 800/day for a
    10,000-unit order, the floor is ceil(10000/800)=13 days, so 14 stands.
    A stated value below the capacity floor is raised to the floor.
    """
    stated = supplier.production_days
    if supplier.capacity_per_day and supplier.capacity_per_day > 0 and quantity > 0:
        capacity_floor = math.ceil(quantity / supplier.capacity_per_day)
        return float(max(stated, capacity_floor))
    return float(stated)


def _supplier_trace(
    supplier: SupplierInput, order: OrderInput, anchor: date
) -> SupplierTrace:
    prod = _capacity_adjusted_production_days(supplier, order.quantity)
    total = (
        supplier.material_ready_days
        + prod
        + supplier.qc_days
        + supplier.logistics_days
    )
    earliest = anchor + timedelta(days=int(math.ceil(total)))
    feasible = order.target_delivery_date is None or earliest <= order.target_delivery_date
    return SupplierTrace(
        supplier_id=supplier.supplier_id,
        material_ready_days=supplier.material_ready_days,
        production_days=supplier.production_days,
        capacity_adjusted_production_days=prod,
        qc_days=supplier.qc_days,
        logistics_days=supplier.logistics_days,
        total_lead_time_days=total,
        confidence=supplier.confidence,
        feasible=feasible,
    )


def _anchor_date(order: OrderInput) -> date:
    return order.evaluation_date or date.today()


def estimate(
    order: OrderInput,
    suppliers: list[SupplierInput],
    constraints: Constraints,
) -> LeadTimeEstimateResponse:
    """Estimate lead time, selecting the fastest supplier that meets the target.

    Edge cases (never crash):
      * 0 suppliers -> feasible=False, structured NO_SUPPLIERS reason.
      * 1 supplier  -> compute + LIMITED_COMPARISON warning.
      * 2 suppliers -> compute + LIMITED_SUPPLIER_POOL warning.
      * 3+ suppliers-> normal comparison.
    """
    anchor = _anchor_date(order)
    warnings: list[Warning] = []
    supplier_count = len(suppliers)

    if supplier_count < constraints.min_supplier_count:
        warnings.append(
            Warning(
                code="BELOW_MIN_SUPPLIER_COUNT",
                message=(
                    f"supplier_count={supplier_count} is below the requested "
                    f"min_supplier_count={constraints.min_supplier_count}"
                ),
            )
        )

    if supplier_count == 0:
        warnings.append(
            Warning(
                code="NO_SUPPLIERS",
                message="No suppliers provided; lead time cannot be estimated.",
            )
        )
        return LeadTimeEstimateResponse(
            status="ok",
            estimated_lead_time_days=None,
            earliest_delivery_date=None,
            feasible=False,
            supplier_count=0,
            selected_supplier_id=None,
            warnings=warnings,
            calculation_trace=[],
        )

    traces = [_supplier_trace(s, order, anchor) for s in suppliers]

    # Deterministic selection: prefer feasible suppliers, then shortest lead
    # time, then highest confidence, then supplier_id for a stable tiebreak.
    def sort_key(t: SupplierTrace) -> tuple:
        return (0 if t.feasible else 1, t.total_lead_time_days, -t.confidence, t.supplier_id)

    ranked = sorted(traces, key=sort_key)
    selected = ranked[0]

    if supplier_count == 1:
        warnings.append(
            Warning(
                code="LIMITED_COMPARISON",
                message="Only one supplier available; no cross-supplier comparison possible.",
            )
        )
    elif supplier_count == 2:
        warnings.append(
            Warning(
                code="LIMITED_SUPPLIER_POOL",
                message="Supplier pool is limited (2 suppliers); comparison breadth is reduced.",
            )
        )

    if not selected.feasible and order.target_delivery_date is not None:
        warnings.append(
            Warning(
                code="TARGET_NOT_MET",
                message=(
                    "No supplier can meet the target delivery date "
                    f"{order.target_delivery_date.isoformat()}."
                ),
            )
        )

    earliest = anchor + timedelta(days=int(math.ceil(selected.total_lead_time_days)))
    return LeadTimeEstimateResponse(
        status="ok",
        estimated_lead_time_days=selected.total_lead_time_days,
        earliest_delivery_date=earliest,
        feasible=selected.feasible,
        supplier_count=supplier_count,
        selected_supplier_id=selected.supplier_id,
        warnings=warnings,
        calculation_trace=traces,
    )
