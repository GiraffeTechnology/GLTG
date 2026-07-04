"""Critical path finder using a slack-based Critical Path Method (CPM).

DEFECT-08: this module previously identified the critical path with a
*longest-finish heuristic* -- it picked the terminal node with the latest
``commitable_finish`` and back-traced the predecessor with the latest finish,
ignoring edge ``lag_days`` and never computing slack. That produced a plausible
bottleneck chain but not a true critical path: with start-to-start / lagged
edges or parallel branches of near-equal length it could mis-attribute the
critical node and omit genuinely zero-slack nodes.

It is now a standard CPM forward/backward pass:

1. **Forward pass** (topological order) -- earliest start/finish (ES/EF),
   honoring ``lag_days`` and ``dependency_type`` (FS / SS / FF; the
   material-ready / approval / capacity variants are treated as finish-to-start
   constraints, matching :class:`DependencyResolver`).
2. **Backward pass** (reverse topological order) -- latest start/finish (LS/LF)
   from the project end.
3. **Slack** = ``LS - ES`` (== ``LF - EF``).
4. **Critical path** = the zero-slack nodes, returned in topological order.

Design decisions for this iteration (see issue DEFECT-08):

- **Percentile**: CPM runs on the *committable* (p90) timeline so ES/EF line up
  with ``commitable_finish``/``commitable_date`` from ``DependencyResolver``.
  Durations are derived from the same flooring rules the resolver uses.
- **Units**: the schedule is computed in whole working days (offsets from the
  project start). Node durations are rounded up exactly as ``add_working_days``
  rounds fractional days, and lags are integers, so slack is an exact integer
  and no floating-point epsilon is needed.
- **Slack surfaced on the node**: each node gets an additive optional
  ``slack_days`` field plus the existing ``is_critical`` flag. The full
  ES/EF/LS/LF schedule is available via :meth:`compute_schedule`.
- **Parallel zero-slack chains**: every zero-slack node is genuinely critical,
  so all of them are returned (in deterministic topological order) rather than
  arbitrarily picking one chain.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..models.enums import DependencyType
from ..models.graph import LeadTimeGraph
from .topological import topological_sort

# Working-day slack tolerance. Offsets are whole working days (durations are
# rounded up, lags are integers), so integer slack is exact; the epsilon only
# guards against accidental float drift and stays at 0 for the integer model.
SLACK_EPSILON = 0

# Fallback p90 duration for a node with no duration estimate. Mirrors the
# ``p50 = p80 = p90 = 2.0`` fallback in ``DependencyResolver``.
_DEFAULT_DURATION_P90 = 2.0


@dataclass
class NodeSchedule:
    """CPM schedule for a single node, in whole working days from project start."""

    node_id: str
    duration: int
    es: int  # earliest start
    ef: int  # earliest finish
    ls: int  # latest start
    lf: int  # latest finish
    slack: int
    is_critical: bool


class CriticalPathFinder:
    """Identifies the critical path via a slack-based CPM forward/backward pass."""

    def compute_schedule(self, graph: LeadTimeGraph) -> dict[str, NodeSchedule]:
        """Return the CPM schedule (ES/EF/LS/LF/slack) for every node.

        Offsets are whole working days measured from the project start. Raises
        ``CyclicDependencyError`` (via :func:`topological_sort`) on a cyclic
        graph.
        """
        if not graph.nodes:
            return {}

        ordered = topological_sort(graph.nodes, graph.edges)
        duration = {n.node_id: self._duration_wd(n) for n in graph.nodes}

        # --- Forward pass: earliest start / finish ---------------------------
        es: dict[str, int] = {}
        ef: dict[str, int] = {}
        for node in ordered:
            nid = node.node_id
            start = 0
            for edge in graph.get_edges_to(nid):
                pred = edge.from_node_id
                if pred not in ef:  # edge references a node outside the graph
                    continue
                start = max(
                    start,
                    self._forward_contribution(edge, es[pred], ef[pred], duration[nid]),
                )
            es[nid] = start
            ef[nid] = start + duration[nid]

        project_end = max(ef.values())

        # --- Backward pass: latest start / finish ----------------------------
        ls: dict[str, int] = {}
        lf: dict[str, int] = {}
        for node in reversed(ordered):
            nid = node.node_id
            latest_finish: float = math.inf
            for edge in graph.get_edges_from(nid):
                succ = edge.to_node_id
                if succ not in ls:  # edge references a node outside the graph
                    continue
                latest_finish = min(
                    latest_finish,
                    self._backward_contribution(edge, ls[succ], lf[succ], duration[nid]),
                )
            if latest_finish is math.inf:  # no successors -> bounded by project end
                latest_finish = project_end
            lf[nid] = int(latest_finish)
            ls[nid] = lf[nid] - duration[nid]

        schedule: dict[str, NodeSchedule] = {}
        for nid in es:
            slack = ls[nid] - es[nid]
            schedule[nid] = NodeSchedule(
                node_id=nid,
                duration=duration[nid],
                es=es[nid],
                ef=ef[nid],
                ls=ls[nid],
                lf=lf[nid],
                slack=slack,
                is_critical=slack <= SLACK_EPSILON,
            )
        return schedule

    def find(self, graph: LeadTimeGraph) -> list[str]:
        """Return the ordered list of node_ids on the critical path.

        Also stamps ``is_critical`` and ``slack_days`` on every node. The path
        is the set of zero-slack nodes, returned in topological order (a stable,
        deterministic ordering).
        """
        if not graph.nodes:
            return []

        schedule = self.compute_schedule(graph)

        for node in graph.nodes:
            sched = schedule.get(node.node_id)
            node.is_critical = sched.is_critical if sched else False
            node.slack_days = sched.slack if sched else None

        ordered = topological_sort(graph.nodes, graph.edges)
        return [n.node_id for n in ordered if schedule[n.node_id].is_critical]

    def find_bottlenecks(self, graph: LeadTimeGraph, critical_path: list[str]) -> list[str]:
        """Return node_ids that are both on the critical path and have high variance.

        High variance = p90 - p50 > 7 days (a week of uncertainty). Unchanged
        from the previous heuristic: variance is orthogonal to slack, so the
        bottleneck definition is preserved and simply consumes the new,
        slack-based critical path.
        """
        bottlenecks: list[str] = []
        node_map = {n.node_id: n for n in graph.nodes}
        for nid in critical_path:
            node = node_map.get(nid)
            if node and node.duration_estimate:
                dur = node.duration_estimate
                variance = dur.p90_days - dur.p50_days
                if variance > 7:
                    bottlenecks.append(nid)
        return bottlenecks

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _duration_wd(node) -> int:
        """Committable (p90) node duration in whole working days.

        Mirrors the flooring and ceiling ``DependencyResolver`` applies so CPM
        offsets stay consistent with ``commitable_finish``.
        """
        dur = node.duration_estimate
        if dur is None:
            p90 = _DEFAULT_DURATION_P90
        else:
            p50 = max(dur.p50_days, 0.5)
            p80 = max(dur.p80_days, p50)
            p90 = max(dur.p90_days, p80)
        return math.ceil(p90)

    @staticmethod
    def _forward_contribution(edge, es_pred: int, ef_pred: int, dur_succ: int) -> int:
        """Earliest-start contribution of ``edge`` to its successor node."""
        lag = edge.lag_days
        dep = edge.dependency_type
        if dep == DependencyType.START_TO_START:
            # successor can start `lag` working days after the predecessor starts
            return es_pred + lag
        if dep == DependencyType.FINISH_TO_FINISH:
            # successor must *finish* >= predecessor finish + lag
            return ef_pred + lag - dur_succ
        # FS and the material-ready / approval / capacity / optional / conditional
        # variants are all "predecessor must finish before successor starts".
        return ef_pred + lag

    @staticmethod
    def _backward_contribution(edge, ls_succ: int, lf_succ: int, dur_pred: int) -> int:
        """Latest-finish contribution of ``edge`` to its predecessor node."""
        lag = edge.lag_days
        dep = edge.dependency_type
        if dep == DependencyType.START_TO_START:
            # LS_pred <= LS_succ - lag  ->  LF_pred = LS_pred + dur_pred
            return ls_succ - lag + dur_pred
        if dep == DependencyType.FINISH_TO_FINISH:
            # LF_pred <= LF_succ - lag
            return lf_succ - lag
        # FS-like: LF_pred <= LS_succ - lag
        return ls_succ - lag
