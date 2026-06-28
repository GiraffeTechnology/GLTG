"""DEFECT-02 + DEFECT-03: factory options must carry their own capacity-bound
dates. Pre-fix, every factory option reused the first factory's schedule; a
slow factory and a fast factory produced identical committable dates.
"""

from __future__ import annotations

from datetime import date

from gltg import LeadTimeGraphEngine, ApparelOrderInput, ParticipantProfile
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
