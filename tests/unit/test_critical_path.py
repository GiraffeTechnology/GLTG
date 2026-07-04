"""Unit tests for CriticalPathFinder and topological_sort."""

from __future__ import annotations

from datetime import date

import pytest

from gltg.errors import CyclicDependencyError
from gltg.graph.critical_path import CriticalPathFinder
from gltg.graph.dependency_resolver import DependencyResolver
from gltg.graph.topological import topological_sort
from gltg.models.duration import DurationEstimate
from gltg.models.edge import LeadTimeEdge
from gltg.models.enums import ApparelNodeType, DependencyType
from gltg.models.graph import LeadTimeGraph
from gltg.models.node import LeadTimeNode


def _make_dur(p50: float) -> DurationEstimate:
    return DurationEstimate(
        p50_days=p50,
        p80_days=p50 * 1.4,
        p90_days=p50 * 2.0,
        min_days=p50 * 0.7,
        max_days=p50 * 3.0,
        confidence=0.5,
    )


def _make_node(node_id: str, p50: float = 5.0) -> LeadTimeNode:
    return LeadTimeNode(
        node_id=node_id,
        node_type=ApparelNodeType.CUTTING,
        duration_estimate=_make_dur(p50),
    )


def _make_edge(from_id: str, to_id: str) -> LeadTimeEdge:
    return LeadTimeEdge(
        edge_id=f"e_{from_id}_{to_id}",
        from_node_id=from_id,
        to_node_id=to_id,
        dependency_type=DependencyType.FINISH_TO_START,
        lag_days=0,
        is_hard_dependency=True,
    )


def _build_and_resolve_graph(nodes, edges, start=date(2026, 1, 5)) -> LeadTimeGraph:
    graph = LeadTimeGraph(
        graph_id="g_test",
        order_id="TEST",
        nodes=nodes,
        edges=edges,
    )
    resolver = DependencyResolver()
    resolver.resolve(graph, start, None)
    return graph


class TestCriticalPathFinder:

    def setup_method(self):
        self.finder = CriticalPathFinder()

    def test_single_path_is_critical(self):
        """In a linear A->B->C graph, all three nodes should be on the critical path."""
        a = _make_node("A", 5.0)
        b = _make_node("B", 5.0)
        c = _make_node("C", 5.0)
        graph = _build_and_resolve_graph([a, b, c], [_make_edge("A", "B"), _make_edge("B", "C")])

        critical = self.finder.find(graph)
        assert len(critical) == 3
        assert "A" in critical
        assert "B" in critical
        assert "C" in critical

    def test_longer_branch_is_critical(self):
        """A->C (10 days) and B->C (2 days); A should be on critical path, not B alone."""
        a = _make_node("A", 10.0)
        b = _make_node("B", 2.0)
        c = _make_node("C", 3.0)
        graph = _build_and_resolve_graph(
            [a, b, c],
            [_make_edge("A", "C"), _make_edge("B", "C")],
        )
        critical = self.finder.find(graph)
        assert "A" in critical
        assert "C" in critical

    def test_critical_nodes_marked(self):
        """After find(), nodes on the critical path should have is_critical=True."""
        a = _make_node("A", 5.0)
        b = _make_node("B", 5.0)
        graph = _build_and_resolve_graph([a, b], [_make_edge("A", "B")])

        critical = self.finder.find(graph)
        critical_ids = set(critical)
        for node in graph.nodes:
            if node.node_id in critical_ids:
                assert node.is_critical is True

    def test_bottlenecks_detected(self):
        """A node with p90 - p50 > 7 days on the critical path should be a bottleneck."""
        # p50=5, p90=14 => variance = 9 > 7
        a = LeadTimeNode(
            node_id="A",
            node_type=ApparelNodeType.FABRIC_ORDERING,
            duration_estimate=DurationEstimate(
                p50_days=5.0, p80_days=10.0, p90_days=14.0,
                min_days=3.0, max_days=20.0, confidence=0.5,
            ),
        )
        b = _make_node("B", 3.0)
        graph = _build_and_resolve_graph([a, b], [_make_edge("A", "B")])

        critical = self.finder.find(graph)
        bottlenecks = self.finder.find_bottlenecks(graph, critical)
        # "A" has high variance so should be in bottlenecks if on critical path
        if "A" in critical:
            assert "A" in bottlenecks

    def test_cyclic_graph_raises(self):
        """topological_sort must raise CyclicDependencyError on a cyclic graph."""
        a = _make_node("A", 5.0)
        b = _make_node("B", 5.0)
        edges = [_make_edge("A", "B"), _make_edge("B", "A")]  # cycle!
        with pytest.raises(CyclicDependencyError):
            topological_sort([a, b], edges)

    def test_empty_graph_returns_empty(self):
        """An empty graph should return an empty critical path."""
        graph = LeadTimeGraph(graph_id="g_empty", order_id="TEST", nodes=[], edges=[])
        critical = self.finder.find(graph)
        assert critical == []


def _dur_p90(p90: float) -> DurationEstimate:
    """Duration whose committable (p90) day count is exactly ``p90``.

    p50/p80 are set below p90 so ``CriticalPathFinder`` derives ``p90`` as the
    node duration, giving hand-computable working-day offsets.
    """
    return DurationEstimate(
        p50_days=max(p90 * 0.5, 0.5),
        p80_days=max(p90 * 0.75, 0.5),
        p90_days=p90,
        min_days=max(p90 * 0.3, 0.5),
        max_days=p90 * 1.5,
        confidence=0.5,
    )


def _node_p90(node_id: str, p90: float) -> LeadTimeNode:
    return LeadTimeNode(
        node_id=node_id,
        node_type=ApparelNodeType.CUTTING,
        duration_estimate=_dur_p90(p90),
    )


def _edge(from_id: str, to_id: str, dep=DependencyType.FINISH_TO_START, lag: int = 0) -> LeadTimeEdge:
    return LeadTimeEdge(
        edge_id=f"e_{from_id}_{to_id}",
        from_node_id=from_id,
        to_node_id=to_id,
        dependency_type=dep,
        lag_days=lag,
        is_hard_dependency=True,
    )


class TestCPMSlack:
    """DEFECT-08: slack-based CPM forward/backward pass acceptance tests.

    Schedules are asserted in whole working-day offsets from the project start,
    independent of any calendar, so the expected values are hand-computable.

    Fixture graph (durations p90 in working days):

        S(2) --FS--> A(5) --FS--> C(4) --FS--> E(2)   [main chain]
        S(2) --SS(lag 1)--> B(3) --FS--> C(4)         [lagged parallel branch]

    Forward pass:  S es0 ef2 | A es2 ef7 | B es1 ef4 | C es7 ef11 | E es11 ef13
    project_end = 13
    Backward pass: E ls11 lf13 | C ls7 lf11 | A ls2 lf7 | B ls4 lf7 | S ls0 lf2
    Slack:         S 0 | A 0 | B 3 | C 0 | E 0
    Critical:      S, A, C, E   (B has slack 3)
    """

    def setup_method(self):
        self.finder = CriticalPathFinder()

    def _fixture(self) -> LeadTimeGraph:
        nodes = [
            _node_p90("S", 2.0),
            _node_p90("A", 5.0),
            _node_p90("B", 3.0),
            _node_p90("C", 4.0),
            _node_p90("E", 2.0),
        ]
        edges = [
            _edge("S", "A"),
            _edge("A", "C"),
            _edge("C", "E"),
            _edge("S", "B", dep=DependencyType.START_TO_START, lag=1),
            _edge("B", "C"),
        ]
        return LeadTimeGraph(graph_id="g_cpm", order_id="TEST", nodes=nodes, edges=edges)

    def test_es_ef_ls_lf_exact(self):
        """Forward/backward pass produces exact hand-computed ES/EF/LS/LF."""
        sched = self.finder.compute_schedule(self._fixture())
        expected = {
            # node: (es, ef, ls, lf)
            "S": (0, 2, 0, 2),
            "A": (2, 7, 2, 7),
            "B": (1, 4, 4, 7),
            "C": (7, 11, 7, 11),
            "E": (11, 13, 11, 13),
        }
        for nid, (es, ef, ls, lf) in expected.items():
            assert (sched[nid].es, sched[nid].ef, sched[nid].ls, sched[nid].lf) == (es, ef, ls, lf), nid

    def test_slack_equals_ls_minus_es(self):
        """Slack == LS - ES == LF - EF for every node; critical nodes have slack 0."""
        sched = self.finder.compute_schedule(self._fixture())
        for s in sched.values():
            assert s.slack == s.ls - s.es
            assert s.slack == s.lf - s.ef
        # Known critical nodes: zero slack.
        for nid in ("S", "A", "C", "E"):
            assert sched[nid].slack == 0
            assert sched[nid].is_critical
        # Known non-critical parallel branch: positive slack.
        assert sched["B"].slack == 3
        assert not sched["B"].is_critical

    def test_critical_path_membership_and_order(self):
        """find() returns exactly the zero-slack nodes, in topological order."""
        graph = self._fixture()
        critical = self.finder.find(graph)
        assert critical == ["S", "A", "C", "E"]
        # is_critical + slack_days are surfaced on the nodes (additive fields).
        by_id = {n.node_id: n for n in graph.nodes}
        assert by_id["B"].is_critical is False
        assert by_id["B"].slack_days == 3
        assert by_id["A"].is_critical is True
        assert by_id["A"].slack_days == 0

    def test_critical_path_shifts_when_branch_grows(self):
        """Lengthening the parallel branch past the main chain moves the critical path."""
        nodes = [
            _node_p90("S", 2.0),
            _node_p90("A", 5.0),
            _node_p90("B", 10.0),  # was 3.0; now dominates the A branch
            _node_p90("C", 4.0),
            _node_p90("E", 2.0),
        ]
        edges = [
            _edge("S", "A"),
            _edge("A", "C"),
            _edge("C", "E"),
            _edge("S", "B", dep=DependencyType.START_TO_START, lag=1),
            _edge("B", "C"),
        ]
        graph = LeadTimeGraph(graph_id="g_cpm2", order_id="TEST", nodes=nodes, edges=edges)
        critical = self.finder.find(graph)
        # Now S -> B -> C -> E is critical and A drops off.
        assert critical == ["S", "B", "C", "E"]
        assert "A" not in critical

    def test_start_to_start_lag_shifts_successor_es(self):
        """A START_TO_START edge shifts the successor ES by exactly its lag."""
        for lag in (0, 1, 4):
            nodes = [_node_p90("S", 5.0), _node_p90("T", 3.0)]
            edges = [_edge("S", "T", dep=DependencyType.START_TO_START, lag=lag)]
            graph = LeadTimeGraph(graph_id=f"g_ss_{lag}", order_id="TEST", nodes=nodes, edges=edges)
            sched = self.finder.compute_schedule(graph)
            # S starts at offset 0; T starts `lag` working days later (not at S's finish).
            assert sched["S"].es == 0
            assert sched["T"].es == sched["S"].es + lag
            # Regression vs the old finish-ignoring trace: ES is the lag, not EF_S.
            assert sched["T"].es == lag

    def test_deterministic_across_runs(self):
        """Identical input yields an identical critical path across repeated runs."""
        runs = [self.finder.find(self._fixture()) for _ in range(5)]
        assert all(r == runs[0] for r in runs)
        assert runs[0] == ["S", "A", "C", "E"]
