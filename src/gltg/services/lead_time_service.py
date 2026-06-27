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
from .baselines import baseline_stage_days


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


def _maybe_apply_baselines(supplier: SupplierInput, order: OrderInput) -> SupplierInput:
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


def _effective_target(order: OrderInput, anchor: date) -> date | None:
    """The deadline GLTG measures feasibility against.

    Prefers an explicit ``target_delivery_date``; otherwise derives one from
    ``deadline_days`` relative to the evaluation anchor. This ensures
    ``deadline_days`` is never silently ignored.
    """
    if order.target_delivery_date is not None:
        return order.target_delivery_date
    if order.deadline_days is not None:
        return anchor + timedelta(days=int(order.deadline_days))
    return None


def _supplier_trace(
    supplier: SupplierInput, order: OrderInput, anchor: date
) -> SupplierTrace:
    supplier = _maybe_apply_baselines(supplier, order)
    prod = _capacity_adjusted_production_days(supplier, order.quantity)
    total = (
        supplier.material_ready_days
        + prod
        + supplier.qc_days
        + supplier.logistics_days
    )
    earliest = anchor + timedelta(days=int(math.ceil(total)))
    target = _effective_target(order, anchor)
    feasible = target is None or earliest <= target
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


def _percentile_bands(total: float, confidence: float) -> tuple[float, float, float, float]:
    """Deterministic p50/p80/p90 + optimistic minimum from a base estimate.

    Lower confidence widens the bands. p50 is the base estimate; p80/p90 add
    uncertainty buffers; minimum_feasible is an optimistic pull-in.
    """
    uncertainty = max(0.0, 1.0 - confidence)
    p50 = float(round(total))
    p80 = float(math.ceil(total * (1.0 + 0.10 + 0.20 * uncertainty)))
    p90 = float(math.ceil(total * (1.0 + 0.20 + 0.35 * uncertainty)))
    minimum = float(math.floor(total * 0.85))
    return p50, p80, p90, minimum


def _risk_level(
    total: float, p80: float, confidence: float, anchor: date, target: date | None
) -> str:
    """Deadline risk: high if median misses target, medium if p80 misses, else low.

    Without a target, risk is derived from confidence alone.
    """
    if target is None:
        if confidence >= 0.75:
            return "low"
        if confidence >= 0.5:
            return "medium"
        return "high"
    median_date = anchor + timedelta(days=int(math.ceil(total)))
    p80_date = anchor + timedelta(days=int(math.ceil(p80)))
    if median_date > target:
        return "high"
    if p80_date > target:
        return "medium"
    return "low"


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

    target = _effective_target(order, anchor)
    if not selected.feasible and target is not None:
        warnings.append(
            Warning(
                code="TARGET_NOT_MET",
                message=(
                    "No supplier can meet the required delivery date "
                    f"{target.isoformat()}."
                ),
            )
        )

    earliest = anchor + timedelta(days=int(math.ceil(selected.total_lead_time_days)))
    p50, p80, p90, minimum = _percentile_bands(selected.total_lead_time_days, selected.confidence)
    risk = _risk_level(
        selected.total_lead_time_days, p80, selected.confidence, anchor, target
    )
    return LeadTimeEstimateResponse(
        status="ok",
        estimated_lead_time_days=selected.total_lead_time_days,
        earliest_delivery_date=earliest,
        feasible=selected.feasible,
        supplier_count=supplier_count,
        selected_supplier_id=selected.supplier_id,
        p50_days=p50,
        p80_days=p80,
        p90_days=p90,
        minimum_feasible_days=minimum,
        risk_level=risk,
        warnings=warnings,
        calculation_trace=traces,
    )
