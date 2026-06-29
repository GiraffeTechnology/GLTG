"""Unit tests for LeadTimeGraphEngine.enumerate_options (DEFECT-TEST-01).

``enumerate_options`` is a public method on the engine that wraps the
PathEnumerator over an already-resolved graph. These tests cover it directly
rather than only through the full ``evaluate`` pipeline.
"""

from __future__ import annotations

from datetime import date

from gltg import LeadTimeGraphEngine
from gltg.graph.dependency_resolver import DependencyResolver
from gltg.models.duration import DurationEstimate
from gltg.models.edge import LeadTimeEdge
from gltg.models.enums import ApparelNodeType, DependencyType
from gltg.models.graph import LeadTimeGraph
from gltg.models.node import LeadTimeNode
from gltg.models.path import DeliveryPathOption

from tests.conftest import make_participant, make_order


def _resolved_graph_with_participant(pid: str) -> LeadTimeGraph:
    """Minimal two-node resolved graph with a participant assigned to all nodes."""
    dur = DurationEstimate(
        p50_days=5.0, p80_days=7.0, p90_days=10.0,
        min_days=3.0, max_days=15.0, confidence=0.5,
    )
    node_a = LeadTimeNode(
        node_id="N_A",
        node_type=ApparelNodeType.CUTTING,
        participant_id=pid,
        duration_estimate=dur,
    )
    node_b = LeadTimeNode(
        node_id="N_B",
        node_type=ApparelNodeType.SEWING,
        participant_id=pid,
        duration_estimate=dur,
    )
    edge = LeadTimeEdge(
        edge_id="e_AB",
        from_node_id="N_A",
        to_node_id="N_B",
        dependency_type=DependencyType.FINISH_TO_START,
        lag_days=0,
        is_hard_dependency=True,
    )
    graph = LeadTimeGraph(
        graph_id="g_enum",
        order_id="ENUM-TEST",
        nodes=[node_a, node_b],
        edges=[edge],
    )
    DependencyResolver().resolve(graph, date(2026, 1, 5), None)
    return graph


def test_enumerate_options_returns_paths_for_valid_input():
    engine = LeadTimeGraphEngine()
    graph = _resolved_graph_with_participant("P1")

    result = engine.enumerate_options(graph)

    assert isinstance(result, list)
    assert len(result) >= 1
    assert all(isinstance(opt, DeliveryPathOption) for opt in result)


def test_enumerate_options_via_full_build_graph():
    engine = LeadTimeGraphEngine()
    order = make_order(
        participants=[make_participant("P1")],
        requested_date=date(2026, 12, 31),
    )
    graph = engine.build_graph(order)

    result = engine.enumerate_options(graph)

    assert len(result) >= 1


def test_enumerate_options_zero_suppliers_returns_empty():
    engine = LeadTimeGraphEngine()
    dur = DurationEstimate(
        p50_days=5.0, p80_days=7.0, p90_days=10.0,
        min_days=3.0, max_days=15.0, confidence=0.5,
    )
    # No participant assigned to any node -> no supplier can own the work.
    node = LeadTimeNode(
        node_id="N_solo",
        node_type=ApparelNodeType.CUTTING,
        participant_id=None,
        duration_estimate=dur,
    )
    graph = LeadTimeGraph(
        graph_id="g_empty",
        order_id="ENUM-EMPTY",
        nodes=[node],
        edges=[],
    )
    DependencyResolver().resolve(graph, date(2026, 1, 5), None)

    result = engine.enumerate_options(graph)

    assert result == []
