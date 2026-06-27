"""HTTP ↔ LeadTimeGraphEngine adapter (DEFECT-01).

The sole bridge between the stable HTTP transport DTOs (`gltg.api.schemas`) and
the deterministic graph engine (`gltg.engine.LeadTimeGraphEngine`). Every `/v1`
endpoint routes through here so that the engine — not the legacy summed-stage
service — is the source of truth for dates, critical path, and options.

The legacy `lead_time_service` / `path_enumeration_service` / `reforecast_service`
modules are retained but demoted to input-prep helpers: this adapter reuses their
capacity-floor, destination/air-sea transit, baseline-synthesis, and event-apply
logic to shape the **engine input**, then lets the engine compute the result.

See `docs/defect-01-schema-mapping.md` for the full mapping.
"""

from __future__ import annotations

from datetime import date

from ..engine import LeadTimeGraphEngine
from ..models.capability import Capability
from ..models.enums import ApparelNodeType, ParticipantType
from ..models.order import ApparelOrderInput
from ..models.packet import DeliveryFeasibilityPacket
from ..models.participant import ParticipantProfile, SupplierResponse
from ..api.schemas import (
    Constraints,
    DeliveryPath,
    LeadTimeEstimateResponse,
    OrderInput,
    PathEnumerateResponse,
    ReforecastEvent,
    ReforecastResponse,
    SupplierInput,
    SupplierTrace,
    Warning,
)
from .lead_time_service import (
    _anchor_date,
    _capacity_adjusted_production_days,
    _effective_target,
    _maybe_apply_baselines,
)
from .reforecast_service import _apply_events

_engine = LeadTimeGraphEngine()

# The HTTP supplier's four stage durations map onto these dominant workflow nodes.
_STAGE_NODES: dict[str, ApparelNodeType] = {
    "material_ready_days": ApparelNodeType.FABRIC_ORDERING,
    "production_days": ApparelNodeType.SEWING,
    "qc_days": ApparelNodeType.FINAL_QC,
    "logistics_days": ApparelNodeType.SHIPMENT,
}

# The participant must hold a capability for every node we inject a response on,
# otherwise the engine leaves the node unassigned and drops the response (it
# matches responses by participant_id). CUTTING/PACKING also keep the participant
# classified as a garment factory for PathEnumerator.
_PARTICIPANT_NODE_TYPES: list[ApparelNodeType] = list(_STAGE_NODES.values()) + [
    ApparelNodeType.CUTTING,
    ApparelNodeType.PACKING,
]


# --------------------------------------------------------------------------- #
# Input prep: HTTP supplier -> single-factory ApparelOrderInput
# --------------------------------------------------------------------------- #
def _effective_stage_days(order: OrderInput, supplier: SupplierInput) -> dict[ApparelNodeType, float]:
    """Normalize a supplier (baseline-fill + capacity floor) and map its four
    stage durations onto the dominant engine workflow nodes."""
    s = _maybe_apply_baselines(supplier, order)
    prod = _capacity_adjusted_production_days(s, order.quantity)
    return {
        ApparelNodeType.FABRIC_ORDERING: float(s.material_ready_days),
        ApparelNodeType.SEWING: float(prod),
        ApparelNodeType.FINAL_QC: float(s.qc_days),
        ApparelNodeType.SHIPMENT: float(s.logistics_days),
    }


def _participant_capabilities(pid: str, capacity_per_day: int | None) -> list[Capability]:
    return [
        Capability(
            capability_id=f"{pid}-{nt.value[:6]}",
            node_type=nt,
            capacity_per_day=capacity_per_day,
        )
        for nt in _PARTICIPANT_NODE_TYPES
    ]


def _build_order_for_supplier(
    order: OrderInput, supplier: SupplierInput, anchor: date
) -> ApparelOrderInput:
    """Construct a single-factory engine order for one supplier."""
    pid = supplier.supplier_id
    participant = ParticipantProfile(
        participant_id=pid,
        name=supplier.name or pid,
        participant_type=ParticipantType.GARMENT_FACTORY,
        capabilities=_participant_capabilities(pid, supplier.capacity_per_day),
        capacity_per_day=supplier.capacity_per_day,
    )
    responses = [
        SupplierResponse(
            response_id=f"{pid}-{nt.value[:6]}",
            participant_id=pid,
            node_type=nt,
            confirmed_days=days,
        )
        for nt, days in _effective_stage_days(order, supplier).items()
        if days > 0
    ]
    return ApparelOrderInput(
        order_id=f"http-estimate-{pid}",
        product_type=order.product_type,
        quantity=order.quantity,
        requested_delivery_date=_effective_target(order, anchor),
        evaluation_date=anchor,
        destination=order.destination,
        participants=[participant],
        supplier_responses=responses,
    )


# --------------------------------------------------------------------------- #
# Packet helpers
# --------------------------------------------------------------------------- #
def _lead_days(d: date | None, anchor: date) -> float | None:
    return float((d - anchor).days) if d is not None else None


def _is_feasible(packet: DeliveryFeasibilityPacket, target: date | None) -> bool:
    from ..models.enums import FeasibilityStatus

    if packet.status == FeasibilityStatus.NO_FEASIBLE_OPTION or packet.commitable_date is None:
        return False
    return target is None or packet.commitable_date <= target


def _risk_level(packet: DeliveryFeasibilityPacket, target: date | None) -> str:
    if target is None:
        otp = packet.on_time_probability
        if otp is None:
            return "unknown"
        return "low" if otp >= 0.8 else ("medium" if otp >= 0.5 else "high")
    c, m = packet.commitable_date, packet.most_likely_date
    if c is not None and c <= target:
        return "low"
    if m is not None and m <= target:
        return "medium"
    return "high"


def _supplier_trace(
    order: OrderInput, supplier: SupplierInput, anchor: date,
    packet: DeliveryFeasibilityPacket, target: date | None,
) -> SupplierTrace:
    s = _maybe_apply_baselines(supplier, order)
    prod = _capacity_adjusted_production_days(s, order.quantity)
    return SupplierTrace(
        supplier_id=supplier.supplier_id,
        material_ready_days=s.material_ready_days,
        production_days=s.production_days,
        capacity_adjusted_production_days=prod,
        qc_days=s.qc_days,
        logistics_days=s.logistics_days,
        # Engine commitable lead time replaces the legacy stage sum.
        total_lead_time_days=_lead_days(packet.commitable_date, anchor) or 0.0,
        confidence=supplier.confidence,
        feasible=_is_feasible(packet, target),
    )


# --------------------------------------------------------------------------- #
# /v1/lead-time/estimate
# --------------------------------------------------------------------------- #
def estimate(
    order: OrderInput, suppliers: list[SupplierInput], constraints: Constraints
) -> LeadTimeEstimateResponse:
    anchor = _anchor_date(order)
    target = _effective_target(order, anchor)
    warnings: list[Warning] = []
    supplier_count = len(suppliers)

    if supplier_count < constraints.min_supplier_count:
        warnings.append(Warning(
            code="BELOW_MIN_SUPPLIER_COUNT",
            message=(f"supplier_count={supplier_count} is below the requested "
                     f"min_supplier_count={constraints.min_supplier_count}"),
        ))

    if supplier_count == 0:
        warnings.append(Warning(
            code="NO_SUPPLIERS",
            message="No suppliers provided; lead time cannot be estimated.",
        ))
        return LeadTimeEstimateResponse(
            status="ok", estimated_lead_time_days=None, earliest_delivery_date=None,
            feasible=False, supplier_count=0, selected_supplier_id=None,
            warnings=warnings, calculation_trace=[],
        )

    evaluated = [(s, _engine.evaluate(_build_order_for_supplier(order, s, anchor))) for s in suppliers]
    traces = [_supplier_trace(order, s, anchor, p, target) for s, p in evaluated]

    # Deterministic selection: feasible-first, shortest commitable lead time,
    # highest stated confidence, then supplier_id.
    def sort_key(item: tuple[SupplierInput, DeliveryFeasibilityPacket]) -> tuple:
        s, p = item
        lead = _lead_days(p.commitable_date, anchor)
        return (
            0 if _is_feasible(p, target) else 1,
            lead if lead is not None else float("inf"),
            -s.confidence,
            s.supplier_id,
        )

    selected_supplier, packet = min(evaluated, key=sort_key)

    if supplier_count == 1:
        warnings.append(Warning(
            code="LIMITED_COMPARISON",
            message="Only one supplier available; no cross-supplier comparison possible.",
        ))
    elif supplier_count == 2:
        warnings.append(Warning(
            code="LIMITED_SUPPLIER_POOL",
            message="Supplier pool is limited (2 suppliers); comparison breadth is reduced.",
        ))

    feasible = _is_feasible(packet, target)
    if not feasible and target is not None:
        warnings.append(Warning(
            code="TARGET_NOT_MET",
            message=f"No supplier can meet the required delivery date {target.isoformat()}.",
        ))

    return LeadTimeEstimateResponse(
        status="ok",
        estimated_lead_time_days=_lead_days(packet.commitable_date, anchor),
        earliest_delivery_date=packet.earliest_feasible_date,
        feasible=feasible,
        supplier_count=supplier_count,
        selected_supplier_id=selected_supplier.supplier_id,
        p50_days=_lead_days(packet.earliest_feasible_date, anchor),
        p80_days=_lead_days(packet.most_likely_date, anchor),
        p90_days=_lead_days(packet.commitable_date, anchor),
        minimum_feasible_days=_lead_days(packet.earliest_feasible_date, anchor),
        risk_level=_risk_level(packet, target),
        most_likely_date=packet.most_likely_date,
        committable_date=packet.commitable_date,
        risk_adjusted_date=packet.risk_adjusted_latest_date,
        on_time_probability=packet.on_time_probability,
        feasibility=packet.status.value,
        warnings=warnings,
        calculation_trace=traces,
    )


# --------------------------------------------------------------------------- #
# /v1/paths/enumerate
# --------------------------------------------------------------------------- #
def _combined_supplier(suppliers: list[SupplierInput]) -> SupplierInput:
    """Synthesize a parallel-split supplier: summed capacity, min stage durations."""
    return SupplierInput(
        supplier_id="parallel:all",
        capacity_per_day=sum(s.capacity_per_day or 0 for s in suppliers) or None,
        material_ready_days=min(s.material_ready_days for s in suppliers),
        production_days=min(s.production_days for s in suppliers),
        qc_days=min(s.qc_days for s in suppliers),
        logistics_days=min(s.logistics_days for s in suppliers),
        confidence=round(sum(s.confidence for s in suppliers) / len(suppliers) * 0.95, 4),
    )


def _path_from_packet(
    path_id: str, mode: str, supplier_ids: list[str], confidence: float,
    packet: DeliveryFeasibilityPacket, anchor: date, target: date | None,
) -> DeliveryPath:
    return DeliveryPath(
        path_id=path_id,
        rank=0,
        mode=mode,
        supplier_ids=supplier_ids,
        estimated_lead_time_days=_lead_days(packet.commitable_date, anchor) or 0.0,
        earliest_delivery_date=packet.earliest_feasible_date,
        feasible=_is_feasible(packet, target),
        confidence=confidence,
        score=0.0,
        warnings=[],
    )


def enumerate_paths(
    order: OrderInput, suppliers: list[SupplierInput], constraints: Constraints
) -> PathEnumerateResponse:
    anchor = _anchor_date(order)
    target = _effective_target(order, anchor)
    warnings: list[Warning] = []
    supplier_count = len(suppliers)

    if supplier_count == 0:
        warnings.append(Warning(code="NO_SUPPLIERS", message="No suppliers provided; no paths to enumerate."))
        return PathEnumerateResponse(status="ok", supplier_count=0, paths=[], warnings=warnings)

    if supplier_count == 1:
        warnings.append(Warning(code="SINGLE_SOURCE_RISK", message="Only one supplier; single-source risk."))
    elif supplier_count == 2:
        warnings.append(Warning(code="LIMITED_SUPPLIER_POOL", message="Limited supplier pool (2 suppliers)."))

    raw: list[DeliveryPath] = []
    for s in suppliers:
        packet = _engine.evaluate(_build_order_for_supplier(order, s, anchor))
        raw.append(_path_from_packet(
            f"single:{s.supplier_id}", "SINGLE_SOURCE", [s.supplier_id], s.confidence, packet, anchor, target))

    if supplier_count >= 2 and constraints.allow_partial_suppliers:
        combined = _combined_supplier(suppliers)
        packet = _engine.evaluate(_build_order_for_supplier(order, combined, anchor))
        raw.append(_path_from_packet(
            "parallel:all", "PARALLEL_SPLIT", sorted(s.supplier_id for s in suppliers),
            combined.confidence, packet, anchor, target))

    def sort_key(p: DeliveryPath) -> tuple:
        return (0 if p.feasible else 1, p.estimated_lead_time_days, -p.confidence, p.path_id)

    ordered = sorted(raw, key=sort_key)
    best_lt = ordered[0].estimated_lead_time_days if ordered else 0.0
    for idx, p in enumerate(ordered, start=1):
        p.rank = idx
        speed = best_lt / p.estimated_lead_time_days if p.estimated_lead_time_days > 0 else 1.0
        p.score = round(0.7 * speed + 0.3 * p.confidence, 4)

    return PathEnumerateResponse(status="ok", supplier_count=supplier_count, paths=ordered, warnings=warnings)


# --------------------------------------------------------------------------- #
# /v1/reforecast
# --------------------------------------------------------------------------- #
def reforecast(
    order: OrderInput, suppliers: list[SupplierInput],
    events: list[ReforecastEvent], constraints: Constraints,
) -> ReforecastResponse:
    baseline = estimate(order, suppliers, constraints)
    updated_suppliers, applied = _apply_events(suppliers, events)
    updated = estimate(order, updated_suppliers, constraints)

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
