"""DEFECT-03: SEWING (production) duration must respond to factory capacity."""

from __future__ import annotations

from gltg.apparel.baselines import get_baseline
from gltg.estimation.duration_estimator import DurationEstimator
from gltg.models.capability import Capability
from gltg.models.enums import ApparelNodeType, ParticipantType
from gltg.models.participant import ParticipantProfile


def _factory(capacity_per_day: int | None) -> ParticipantProfile:
    caps = []
    if capacity_per_day is not None:
        caps = [Capability(capability_id="c", node_type=ApparelNodeType.SEWING,
                           capacity_per_day=capacity_per_day)]
    return ParticipantProfile(
        participant_id="F", name="F", participant_type=ParticipantType.GARMENT_FACTORY,
        capacity_per_day=capacity_per_day, capabilities=caps,
    )


def _sewing_p50(capacity_per_day: int | None, quantity: int = 10_000) -> float:
    est = DurationEstimator().estimate(
        node_type=ApparelNodeType.SEWING,
        participant=_factory(capacity_per_day),
        supplier_response=None,
        memory_records=[],
        progress_events=[],
        quantity=quantity,
    )
    return est.p50_days


def test_capacity_floor_makes_slow_factory_much_slower():
    fast = _sewing_p50(5_000)   # ceil(10000/5000) = 2
    slow = _sewing_p50(200)     # ceil(10000/200)  = 50
    assert slow >= fast + 40


def test_no_capacity_falls_back_to_quantity_baseline():
    # Without capacity, SEWING uses the quantity-scaled category proxy.
    assert _sewing_p50(None) == get_baseline(ApparelNodeType.SEWING, 10_000)["p50"]


def test_get_baseline_sewing_is_capacity_bound():
    assert get_baseline(ApparelNodeType.SEWING, 10_000, capacity_per_day=5_000)["p50"] == 2
    assert get_baseline(ApparelNodeType.SEWING, 10_000, capacity_per_day=200)["p50"] == 50
    # Non-production nodes ignore capacity.
    base = get_baseline(ApparelNodeType.FINAL_QC, 10_000, capacity_per_day=200)
    assert base == get_baseline(ApparelNodeType.FINAL_QC, 10_000)
