"""Deterministic delivery-path enumeration service.

Produces a deterministically ranked set of execution paths from the supplier
pool. Two path families are generated:

  * SINGLE_SOURCE  -- one path per supplier (the whole order from one supplier).
  * PARALLEL_SPLIT -- one combined path using all suppliers in parallel, only
                      when constraints allow partial suppliers and 2+ suppliers
                      exist. Production time is bounded by combined capacity.

Ranking is fully deterministic: feasible-first, then shortest lead time, then
highest confidence, then path_id.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from ..api.schemas import (
    Constraints,
    DeliveryPath,
    OrderInput,
    PathEnumerateResponse,
    SupplierInput,
    Warning,
)
from .lead_time_service import _anchor_date, _capacity_adjusted_production_days


def _single_source_path(
    supplier: SupplierInput, order: OrderInput, anchor: date
) -> tuple[float, float, date, bool]:
    prod = _capacity_adjusted_production_days(supplier, order.quantity)
    total = supplier.material_ready_days + prod + supplier.qc_days + supplier.logistics_days
    earliest = anchor + timedelta(days=int(math.ceil(total)))
    feasible = order.target_delivery_date is None or earliest <= order.target_delivery_date
    return total, supplier.confidence, earliest, feasible


def _parallel_split_path(
    suppliers: list[SupplierInput], order: OrderInput, anchor: date
) -> tuple[float, float, date, bool]:
    """Combined parallel path: stages run with the slowest material/qc/logistics
    but production is shared across combined daily capacity."""
    combined_capacity = sum(s.capacity_per_day or 0 for s in suppliers)
    if combined_capacity > 0 and order.quantity > 0:
        production_days = float(math.ceil(order.quantity / combined_capacity))
    else:
        production_days = max(s.production_days for s in suppliers)
    material = max(s.material_ready_days for s in suppliers)
    qc = max(s.qc_days for s in suppliers)
    logistics = max(s.logistics_days for s in suppliers)
    total = material + production_days + qc + logistics
    # Combined confidence is the mean (deterministic), slightly discounted for
    # coordination overhead across multiple suppliers.
    mean_conf = sum(s.confidence for s in suppliers) / len(suppliers)
    confidence = round(mean_conf * 0.95, 4)
    earliest = anchor + timedelta(days=int(math.ceil(total)))
    feasible = order.target_delivery_date is None or earliest <= order.target_delivery_date
    return total, confidence, earliest, feasible


def enumerate_paths(
    order: OrderInput,
    suppliers: list[SupplierInput],
    constraints: Constraints,
) -> PathEnumerateResponse:
    anchor = _anchor_date(order)
    warnings: list[Warning] = []
    supplier_count = len(suppliers)

    if supplier_count == 0:
        warnings.append(
            Warning(code="NO_SUPPLIERS", message="No suppliers provided; no paths to enumerate.")
        )
        return PathEnumerateResponse(status="ok", supplier_count=0, paths=[], warnings=warnings)

    if supplier_count == 1:
        warnings.append(
            Warning(code="SINGLE_SOURCE_RISK", message="Only one supplier; single-source risk.")
        )
    elif supplier_count == 2:
        warnings.append(
            Warning(code="LIMITED_SUPPLIER_POOL", message="Limited supplier pool (2 suppliers).")
        )

    raw_paths: list[DeliveryPath] = []

    for s in suppliers:
        total, conf, earliest, feasible = _single_source_path(s, order, anchor)
        raw_paths.append(
            DeliveryPath(
                path_id=f"single:{s.supplier_id}",
                rank=0,
                mode="SINGLE_SOURCE",
                supplier_ids=[s.supplier_id],
                estimated_lead_time_days=total,
                earliest_delivery_date=earliest,
                feasible=feasible,
                confidence=conf,
                score=0.0,
                warnings=[],
            )
        )

    if supplier_count >= 2 and constraints.allow_partial_suppliers:
        total, conf, earliest, feasible = _parallel_split_path(suppliers, order, anchor)
        raw_paths.append(
            DeliveryPath(
                path_id="parallel:all",
                rank=0,
                mode="PARALLEL_SPLIT",
                supplier_ids=sorted(s.supplier_id for s in suppliers),
                estimated_lead_time_days=total,
                earliest_delivery_date=earliest,
                feasible=feasible,
                confidence=conf,
                score=0.0,
                warnings=[],
            )
        )

    # Deterministic ranking and a normalized score (1.0 best).
    def sort_key(p: DeliveryPath) -> tuple:
        return (0 if p.feasible else 1, p.estimated_lead_time_days, -p.confidence, p.path_id)

    ordered = sorted(raw_paths, key=sort_key)
    best_lt = ordered[0].estimated_lead_time_days if ordered else 0.0
    for idx, p in enumerate(ordered, start=1):
        p.rank = idx
        # Score blends speed (vs best) and confidence; deterministic.
        speed = best_lt / p.estimated_lead_time_days if p.estimated_lead_time_days > 0 else 1.0
        p.score = round(0.7 * speed + 0.3 * p.confidence, 4)

    return PathEnumerateResponse(
        status="ok",
        supplier_count=supplier_count,
        paths=ordered,
        warnings=warnings,
    )
