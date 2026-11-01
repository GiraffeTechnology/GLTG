"""Planning dates are explicit inputs; wall-clock defaults remain opt-in."""

from datetime import date

import pytest

import gltg.engine as engine_module
from gltg import LeadTimeGraphEngine
from gltg.models.enums import FeasibilityStatus
from tests.conftest import make_order, make_participant


ANCHOR = date(2026, 6, 27)
DEADLINE = date(2026, 12, 31)


def _order(supplier_count, evaluation_date=None):
    return make_order(
        order_id="CLOCK-REGRESSION",
        quantity=2000,
        participants=[make_participant(f"P{i}") for i in range(supplier_count)],
        requested_date=DEADLINE,
        evaluation_date=evaluation_date,
    )


def _planning_result(packet):
    # Run timestamps and generated IDs are metadata, not planning dates.
    return (
        packet.status,
        packet.earliest_feasible_date,
        packet.most_likely_date,
        packet.commitable_date,
        packet.risk_adjusted_latest_date,
        [
            (option.participant_combination, option.earliest_feasible_date,
             option.most_likely_date, option.commitable_date)
            for option in packet.options
        ],
    )


@pytest.mark.parametrize("supplier_count", [1, 2, 3])
@pytest.mark.parametrize("wall_date", [date(2026, 11, 1), date(2027, 1, 1)])
def test_explicit_anchor_preserves_dates_after_wall_clock_advances(
    monkeypatch, supplier_count, wall_date,
):
    expected = LeadTimeGraphEngine().evaluate(_order(supplier_count, ANCHOR))

    class AdvancedDate(date):
        @classmethod
        def today(cls):
            return wall_date

    monkeypatch.setattr(engine_module, "date", AdvancedDate)
    actual = LeadTimeGraphEngine().evaluate(_order(supplier_count, ANCHOR))
    assert expected.status != FeasibilityStatus.NO_FEASIBLE_OPTION
    assert len(actual.options) == supplier_count
    assert actual.commitable_date is not None
    assert _planning_result(actual) == _planning_result(expected)


def test_explicit_anchor_does_not_read_today(monkeypatch):
    class ForbiddenToday(date):
        @classmethod
        def today(cls):
            raise AssertionError("An explicit planning anchor must not read today()")

    monkeypatch.setattr(engine_module, "date", ForbiddenToday)
    packet = LeadTimeGraphEngine().evaluate(_order(1, ANCHOR))
    assert packet.status == FeasibilityStatus.LIMITED_OPTIONS
    assert packet.commitable_date is not None


@pytest.mark.parametrize("supplier_count", [1, 2, 3])
def test_explicit_anchor_after_deadline_remains_infeasible(supplier_count):
    packet = LeadTimeGraphEngine().evaluate(_order(supplier_count, date(2027, 1, 1)))
    assert packet.status == FeasibilityStatus.NO_FEASIBLE_OPTION
    assert packet.options == []
    assert packet.commitable_date is None


@pytest.mark.parametrize("wall_date", [ANCHOR, date(2027, 1, 1)])
def test_missing_anchor_keeps_current_date_default(monkeypatch, wall_date):
    class CurrentDate(date):
        @classmethod
        def today(cls):
            return wall_date

    monkeypatch.setattr(engine_module, "date", CurrentDate)
    implicit_order = _order(1)
    assert implicit_order.evaluation_date is None
    implicit = LeadTimeGraphEngine().evaluate(implicit_order)
    explicit = LeadTimeGraphEngine().evaluate(_order(1, wall_date))
    assert _planning_result(implicit) == _planning_result(explicit)
    if wall_date > DEADLINE:
        assert implicit.status == FeasibilityStatus.NO_FEASIBLE_OPTION
        assert implicit.commitable_date is None
