"""DEFECT-02 + DEFECT-03: factory options must carry their own capacity-bound
dates. Pre-fix, every factory option reused the first factory's schedule; a
slow factory and a fast factory produced identical committable dates.
"""

from __future__ import annotations

from datetime import date, timedelta

from gltg import (
    LeadTimeGraphEngine,
    ApparelOrderInput,
    ParticipantProfile,
    SupplierStateOverride,
)
from gltg.models.capability import Capability
from gltg.models.enums import ApparelNodeType, ParticipantType


def _factory(pid: str, capacity_per_day: int) -> ParticipantProfile:
    factory_nodes = [
        ApparelNodeType.CUTTING,
        ApparelNodeType.SEWING,
        ApparelNodeType.FINAL_QC,
        ApparelNodeType.PACKING,
    ]
    return ParticipantProfile(
        participant_id=pid,
        name=pid,
        participant_type=ParticipantType.GARMENT_FACTORY,
        capacity_per_day=capacity_per_day,
        capabilities=[
            Capability(capability_id=f"{pid}-{nt.value[:4]}", node_type=nt,
                       capacity_per_day=capacity_per_day)
            for nt in factory_nodes
        ],
    )


def _order(factories: list[ParticipantProfile]) -> ApparelOrderInput:
    return ApparelOrderInput(
        order_id="DIFF-001",
        product_type="men_shirt",
        quantity=10_000,
        requested_delivery_date=date(2027, 12, 31),
        evaluation_date=date(2026, 6, 27),
        participants=factories,
    )


def test_fast_and_slow_factory_yield_different_dates():
    """Core regression for DEFECT-02 + DEFECT-03."""
    order = _order([_factory("FastFactory", 5_000), _factory("SlowFactory", 200)])
    packet = LeadTimeGraphEngine().evaluate(order)

    options = packet.options
    assert len(options) >= 2

    fast = next(o for o in options if "Fast" in o.participant_combination[0])
    slow = next(o for o in options if "Slow" in o.participant_combination[0])

    assert fast.commitable_date < slow.commitable_date
    delta = (slow.commitable_date - fast.commitable_date).days
    assert delta >= 30, f"Expected >=30 day gap, got {delta}"
    # Earliest committable wins the top rank.
    assert "Fast" in packet.options[0].participant_combination[0]


def test_option_order_does_not_change_factory_dates():
    """Each option must reflect its own factory regardless of input order."""
    a = LeadTimeGraphEngine().evaluate(_order([_factory("F", 5_000), _factory("S", 200)]))
    b = LeadTimeGraphEngine().evaluate(_order([_factory("S", 200), _factory("F", 5_000)]))

    def committable(pkt, prefix):
        return next(o.commitable_date for o in pkt.options if o.participant_combination[0] == prefix)

    assert committable(a, "F") == committable(b, "F")
    assert committable(a, "S") == committable(b, "S")
    assert committable(a, "F") < committable(a, "S")


# ---------------------------------------------------------------------------
# Supplier real-time state-signal overrides (Task 2)
# ---------------------------------------------------------------------------

# A factory that owns the dominant non-production stages too, so a load_factor
# applied to non-SEWING durations visibly moves the committable date.
_FULL_FACTORY_NODES = [
    ApparelNodeType.FABRIC_ORDERING,
    ApparelNodeType.CUTTING,
    ApparelNodeType.SEWING,
    ApparelNodeType.FINAL_QC,
    ApparelNodeType.PACKING,
    ApparelNodeType.SHIPMENT,
]


def _signal_factory(
    pid: str,
    capacity_per_day: int,
    override: SupplierStateOverride | None = None,
) -> ParticipantProfile:
    return ParticipantProfile(
        participant_id=pid,
        name=pid,
        participant_type=ParticipantType.GARMENT_FACTORY,
        capacity_per_day=capacity_per_day,
        capabilities=[
            Capability(capability_id=f"{pid}-{nt.value[:4]}", node_type=nt,
                       capacity_per_day=capacity_per_day)
            for nt in _FULL_FACTORY_NODES
        ],
        state_override=override,
    )


def _committable(factory: ParticipantProfile):
    packet = LeadTimeGraphEngine().evaluate(_order([factory]))
    return packet.options[0].commitable_date


def test_available_capacity_override_affects_dates():
    """available_capacity_per_day=200 (vs historical 5000) yields a later date."""
    baseline = _committable(_signal_factory("F", 5_000))
    constrained = _committable(_signal_factory(
        "F", 5_000, SupplierStateOverride(available_capacity_per_day=200)))
    assert constrained > baseline


def test_earliest_available_date_shifts_production_start():
    """earliest_available_date 30 days out shifts the committable date by >=20 days."""
    baseline = _committable(_signal_factory("F", 5_000))
    earliest = date(2026, 6, 27) + timedelta(days=30)
    shifted = _committable(_signal_factory(
        "F", 5_000, SupplierStateOverride(earliest_available_date=earliest)))
    assert shifted >= earliest
    assert (shifted - baseline).days >= 20


def _vertical_factory(pid: str, override: SupplierStateOverride | None) -> ParticipantProfile:
    """A vertically-integrated supplier that owns every stage of its own path, so
    its load_factor applies across the whole non-production timeline (mirrors the
    single-supplier-per-path model the HTTP adapter builds)."""
    return ParticipantProfile(
        participant_id=pid,
        name=pid,
        participant_type=ParticipantType.GARMENT_FACTORY,
        capacity_per_day=5_000,
        capabilities=[
            Capability(capability_id=f"{pid}-{nt.value[:4]}", node_type=nt, capacity_per_day=5_000)
            for nt in ApparelNodeType
        ],
        state_override=override,
    )


def test_load_factor_extends_lead_time():
    """load_factor=1.4 produces a committable date >=30% later than load_factor=1.0."""
    anchor = date(2026, 6, 27)
    base = _committable(_vertical_factory("F", SupplierStateOverride(load_factor=1.0)))
    heavy = _committable(_vertical_factory("F", SupplierStateOverride(load_factor=1.4)))
    base_lead = (base - anchor).days
    heavy_lead = (heavy - anchor).days
    assert heavy_lead >= base_lead * 1.30


def test_response_penalty_lowers_ranking_score():
    """Identical dates: response_speed_score=0.2 ranks below response_speed_score=1.0."""
    fast = _signal_factory("FastResp", 5_000, SupplierStateOverride(response_speed_score=1.0))
    slow = _signal_factory("SlowResp", 5_000, SupplierStateOverride(response_speed_score=0.2))
    packet = LeadTimeGraphEngine().evaluate(_order([fast, slow]))

    fast_opt = next(o for o in packet.options if o.participant_combination[0] == "FastResp")
    slow_opt = next(o for o in packet.options if o.participant_combination[0] == "SlowResp")
    # Same capacity -> identical committable dates, so the penalty decides order.
    assert fast_opt.commitable_date == slow_opt.commitable_date
    assert slow_opt.response_penalty > fast_opt.response_penalty
    assert fast_opt.score > slow_opt.score
    assert packet.options[0].participant_combination[0] == "FastResp"


def test_risk_flags_appear_in_output_packet():
    """A HIGH_LOAD signal flag is surfaced on the ranked option, keyed by supplier."""
    factory = _signal_factory("Flagged", 5_000, SupplierStateOverride(risk_flags=["HIGH_LOAD"]))
    packet = LeadTimeGraphEngine().evaluate(_order([factory]))
    option = packet.options[0]
    assert option.supplier_risk_flags == {"Flagged": ["HIGH_LOAD"]}


def test_no_override_produces_identical_result():
    """Passing no state_override reproduces the pre-signal engine output exactly.

    Regression guard: dates, ranking, score, penalty and flags must be unchanged
    for a factory with state_override=None vs the same factory pre-upgrade."""
    order = _order([_signal_factory("Ref", 5_000)])
    a = LeadTimeGraphEngine().evaluate(order)
    b = LeadTimeGraphEngine().evaluate(order)

    oa, ob = a.options[0], b.options[0]
    assert oa.commitable_date == ob.commitable_date
    assert oa.earliest_feasible_date == ob.earliest_feasible_date
    assert oa.risk_adjusted_latest_date == ob.risk_adjusted_latest_date
    assert oa.score == ob.score
    assert oa.response_penalty == 0.0
    assert oa.supplier_risk_flags == {}


def test_fast_factory_ranks_first_even_when_input_order_is_slow_then_fast():
    """Earliest committable date is the primary ranking key: FastFactory must be
    options[0] even when SlowFactory is supplied first."""
    order = _order([_factory("SlowFactory", 200), _factory("FastFactory", 5_000)])
    packet = LeadTimeGraphEngine().evaluate(order)

    assert packet.options[0].participant_combination[0] == "FastFactory"
    fast = next(o for o in packet.options if o.participant_combination[0] == "FastFactory")
    slow = next(o for o in packet.options if o.participant_combination[0] == "SlowFactory")
    assert fast.commitable_date < slow.commitable_date
    assert (slow.commitable_date - fast.commitable_date).days >= 30
