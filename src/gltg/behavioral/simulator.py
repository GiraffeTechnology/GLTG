"""Rule-based MVP for GLTG v2 behavior-aware lead-time simulation."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

from .schemas import (
    GLTGComponentBreakdown,
    GLTGPersistenceRef,
    GLTGQuantiles,
    GLTGRiskOutput,
    GLTGSimulationRequestV2,
    GLTGSimulationResponseV2,
    GLTGWarningV2,
)

MODEL_VERSION = "gltg-hybrid-v0.1.0"
RULE_VERSION = "behavior-rules-v0.1.0"
Z80 = 0.8416212335729143
Z90 = 1.2815515655446004
SIGMA_MIN = 0.05
SIGMA_MAX = 0.85
DEFAULT_DAILY_CAPACITY = 500
PRODUCTION_EFFICIENCY = 0.85

SEA_TRANSIT_DAYS = {
    "vancouver": 18,
    "los angeles": 14,
    "new york": 28,
    "london": 25,
    "rotterdam": 22,
}
AIR_TRANSIT_DAYS = {
    "vancouver": 3,
    "los angeles": 2,
    "new york": 3,
    "london": 2,
    "rotterdam": 2,
}


@dataclass
class AdjustmentState:
    supplier_response_buffer: float = 0.0
    supplier_uncertainty_buffer: float = 0.0
    buyer_decision_buffer: float = 0.0
    risk_buffer: float = 0.0
    delta_sigma: float = 0.0
    risk_points: int = 0
    fallback_supplier_required: bool = False
    manual_review_required: bool = False
    warnings: list[GLTGWarningV2] = field(default_factory=list)
    explanations: list[dict[str, Any]] = field(default_factory=list)


class BehavioralLeadTimeSimulator:
    """Composes baseline quantiles with deterministic behavior adjustments."""

    def simulate(self, req: GLTGSimulationRequestV2) -> GLTGSimulationResponseV2:
        base_q, components, baseline_source = self._baseline(req)
        state = self._behavior_adjustments(req)

        shift = state.supplier_response_buffer + state.buyer_decision_buffer
        uncertainty = state.supplier_uncertainty_buffer + state.risk_buffer
        if self._has_distribution(req):
            p50, p80, p90 = self._compose_pseudo_lognormal(base_q, shift, uncertainty, state.delta_sigma)
            composer = "pseudo_lognormal"
        else:
            p50, p80, p90 = self._compose_deterministic_fallback(base_q, shift, uncertainty)
            composer = "deterministic_fallback"
        p50, p80, p90 = self._repair_monotonic(p50, p80, p90)

        selected = {"P50": p50, "P80": p80, "P90": p90}[req.constraints.lead_time_confidence]
        risk = self._risk(req, selected, p50, p80, p90, state)
        components.supplier_response_buffer_days = round(state.supplier_response_buffer, 2)
        components.supplier_uncertainty_buffer_days = round(state.supplier_uncertainty_buffer, 2)
        components.buyer_decision_buffer_days = round(state.buyer_decision_buffer, 2)
        components.risk_buffer_days = round(state.risk_buffer, 2)

        warnings = list(state.warnings)
        if not req.source_observation_ids:
            warnings.append(GLTGWarningV2(
                code="MISSING_SOURCE_OBSERVATIONS",
                severity="low",
                message="No source_observation_ids were provided; lineage is incomplete.",
            ))
        warnings.append(GLTGWarningV2(
            code="PERSISTENCE_NOT_CONFIGURED",
            severity="low",
            message="GLTG run id is generated, but giraffe-db persistence is not configured in this service build.",
        ))

        return GLTGSimulationResponseV2(
            ok=True,
            gltg_run_id=self._run_id(req),
            model_version=MODEL_VERSION,
            rule_version=RULE_VERSION,
            calibration_version="none",
            quantiles=GLTGQuantiles(
                p50_days=round(p50, 2),
                p80_days=round(p80, 2),
                p90_days=round(p90, 2),
            ),
            components=components,
            risk=risk,
            explanation_json={
                "summary": self._summary(risk, baseline_source),
                "baseline_source": baseline_source,
                "composer": composer,
                "composition_parameters": {
                    "central_shift_days": round(shift, 2),
                    "uncertainty_buffer_days": round(uncertainty, 2),
                    "delta_sigma": round(state.delta_sigma, 4),
                },
                "adjustments": state.explanations,
                "source_observation_ids": req.source_observation_ids,
            },
            warnings=warnings,
            persistence=GLTGPersistenceRef(
                persisted_to_giraffe_db=False,
                gltg_behavior_input_id=None,
            ),
        )

    def _compose_pseudo_lognormal(
        self,
        base_q: GLTGQuantiles,
        shift_days: float,
        uncertainty_days: float,
        delta_sigma: float,
    ) -> tuple[float, float, float]:
        base_p50 = max(base_q.p50_days, 0.1)
        base_p90 = max(base_q.p90_days, base_p50)
        mu = math.log(base_p50)
        sigma = (math.log(base_p90) - math.log(base_p50)) / Z90 if base_p90 > base_p50 else SIGMA_MIN
        mu_star = mu + math.log((base_p50 + shift_days) / base_p50)
        sigma_star = min(SIGMA_MAX, max(SIGMA_MIN, sigma * math.exp(delta_sigma)))
        p50 = math.exp(mu_star)
        p80 = math.exp(mu_star + sigma_star * Z80) + 0.8 * uncertainty_days
        p90 = math.exp(mu_star + sigma_star * Z90) + 1.2 * uncertainty_days
        return p50, p80, p90

    @staticmethod
    def _compose_deterministic_fallback(
        base_q: GLTGQuantiles,
        shift_days: float,
        uncertainty_days: float,
    ) -> tuple[float, float, float]:
        return (
            base_q.p50_days + shift_days,
            base_q.p80_days + shift_days + 0.8 * uncertainty_days,
            base_q.p90_days + shift_days + 1.2 * uncertainty_days,
        )

    def _baseline(
        self, req: GLTGSimulationRequestV2
    ) -> tuple[GLTGQuantiles, GLTGComponentBreakdown, str]:
        hist = req.historical_baseline
        if self._has_distribution(req):
            p50, p80, p90 = self._repair_monotonic(
                float(hist.baseline_p50_days),
                float(hist.baseline_p80_days),
                float(hist.baseline_p90_days),
            )
            return (
                GLTGQuantiles(p50_days=p50, p80_days=p80, p90_days=p90),
                self._components_from_request(req),
                hist.baseline_source or "historical_baseline",
            )

        components = self._components_from_request(req)
        base_total = (
            components.base_procurement_days
            + components.base_production_days
            + components.logistics_buffer_days
        )
        if req.supplier.supplier_stated_lead_time_days:
            base_total = max(base_total, float(req.supplier.supplier_stated_lead_time_days))
        p50 = max(base_total, 1.0)
        p80 = p50 * 1.18
        p90 = p50 * 1.35
        return GLTGQuantiles(p50_days=p50, p80_days=p80, p90_days=p90), components, "gltg_requirement_baseline"

    @staticmethod
    def _has_distribution(req: GLTGSimulationRequestV2) -> bool:
        hist = req.historical_baseline
        return bool(hist.baseline_p50_days and hist.baseline_p80_days and hist.baseline_p90_days)

    def _components_from_request(self, req: GLTGSimulationRequestV2) -> GLTGComponentBreakdown:
        supplier = req.supplier
        order = req.order
        stages = _baseline_stage_days(
            order.quantity,
            order.destination,
            order.logistics_mode,
            supplier.capacity_per_day,
        )
        procurement = float(supplier.material_ready_days if supplier.material_ready_days is not None else stages["material_ready_days"])
        production = float(supplier.production_days if supplier.production_days is not None else stages["production_days"])
        qc = float(supplier.qc_days if supplier.qc_days is not None else stages["qc_days"])
        logistics = float(supplier.logistics_days if supplier.logistics_days is not None else stages["logistics_days"])
        return GLTGComponentBreakdown(
            base_production_days=round(production, 2),
            base_procurement_days=round(procurement + qc, 2),
            logistics_buffer_days=round(logistics, 2),
        )

    def _behavior_adjustments(self, req: GLTGSimulationRequestV2) -> AdjustmentState:
        s = req.behavior_features.supplier
        b = req.behavior_features.buyer
        state = AdjustmentState()

        self._supplier_response_delay(s.response_delay_ratio, state)
        self._business_hours_delay(s.business_hours_delay_ratio, state)
        self._quote_completeness(s.quote_completeness_score, state)
        self._lead_time_revisions(s.lead_time_revision_count, state)
        self._upstream_signal(s.upstream_confirmation_signal, state)
        self._supplier_load(s.supplier_current_load_signal, state)
        self._requirement_changes(b.requirement_change_count, state)
        self._buyer_decision_delay(b.buyer_decision_delay_score, state)

        relationship = req.behavior_features.pair.relationship_strength_score
        if relationship is not None and relationship < 0.3:
            state.risk_points += 1
            self._warn(state, "WEAK_BUYER_SUPPLIER_RELATIONSHIP", "low", "Buyer-supplier relationship strength is low.")
            self._explain(state, "relationship_strength_score", relationship, "+1 risk level pressure", "Weak buyer-supplier history increases execution risk.")

        historical_error = req.historical_baseline.historical_quoted_vs_actual_error_days
        if historical_error is not None and historical_error > 5:
            days = min(5.0, historical_error * 0.4)
            state.supplier_uncertainty_buffer += days
            state.risk_points += 1
            self._warn(state, "HISTORICAL_LEADTIME_ERROR_HIGH", "medium", "Historical quoted-vs-actual lead-time error is high.")
            self._explain(
                state,
                "historical_quoted_vs_actual_error_days",
                historical_error,
                f"+{round(days, 2)} supplier_uncertainty_buffer_days",
                "Historical supplier/category lead-time error is above 5 days.",
            )

        if state.delta_sigma > 0:
            state.risk_buffer += round(state.delta_sigma * 10, 2)
        return state

    def _supplier_response_delay(self, ratio: float | None, state: AdjustmentState) -> None:
        if ratio is None:
            return
        if ratio < 1.2:
            self._explain(state, "supplier_response_delay_ratio", ratio, "+0 supplier_response_buffer_days", "Supplier response speed is near baseline.")
        elif ratio < 2.0:
            state.supplier_response_buffer += 1
            state.delta_sigma += 0.03
            self._warn(state, "SUPPLIER_RESPONSE_DELAY_ANOMALY", "low", "Supplier response is moderately slower than baseline.")
            self._explain(state, "supplier_response_delay_ratio", ratio, "+1 supplier_response_buffer_days", "Response delay ratio is between 1.2 and 2.0.")
        elif ratio < 3.0:
            state.supplier_response_buffer += 2
            state.delta_sigma += 0.07
            state.risk_points += 1
            self._warn(state, "SUPPLIER_RESPONSE_DELAY_ANOMALY", "medium", "Supplier response is materially slower than baseline.")
            self._explain(state, "supplier_response_delay_ratio", ratio, "+2 supplier_response_buffer_days", "Response delay ratio is between 2.0 and 3.0.")
        else:
            days = min(5.0, max(3.0, math.ceil(ratio)))
            state.supplier_response_buffer += days
            state.delta_sigma += 0.12
            state.risk_points += 2
            state.fallback_supplier_required = True
            self._warn(state, "SUPPLIER_RESPONSE_DELAY_ANOMALY", "medium", "Supplier response is at least 3x slower than baseline.")
            self._explain(state, "supplier_response_delay_ratio", ratio, f"+{int(days)} supplier_response_buffer_days", "Response delay ratio is 3.0 or higher.")

    def _business_hours_delay(self, ratio: float | None, state: AdjustmentState) -> None:
        if ratio is None:
            return
        if 1.5 <= ratio < 3.0:
            state.supplier_response_buffer += 1
            self._explain(state, "business_hours_delay_ratio", ratio, "+1 supplier_response_buffer_days", "Supplier is slow during business hours.")
        elif ratio >= 3.0:
            state.supplier_response_buffer += 2
            state.manual_review_required = True
            self._warn(state, "BUSINESS_HOURS_DELAY", "medium", "Business-hours response delay is high.")
            self._explain(state, "business_hours_delay_ratio", ratio, "+2 supplier_response_buffer_days", "Business-hours delay ratio is 3.0 or higher.")

    def _quote_completeness(self, score: float | None, state: AdjustmentState) -> None:
        if score is None:
            return
        if score >= 0.9:
            self._explain(state, "quote_completeness_score", score, "+0 supplier_uncertainty_buffer_days", "Quote completeness is high.")
        elif score >= 0.7:
            state.supplier_uncertainty_buffer += 1
            self._explain(state, "quote_completeness_score", score, "+1 supplier_uncertainty_buffer_days", "Quote has moderate missing detail.")
        elif score >= 0.5:
            state.supplier_uncertainty_buffer += 2
            state.delta_sigma += 0.08
            state.risk_points += 1
            self._warn(state, "QUOTE_INCOMPLETE", "medium", "Quote completeness is below 0.70.")
            self._explain(state, "quote_completeness_score", score, "+2 supplier_uncertainty_buffer_days", "Quote completeness is between 0.50 and 0.70.")
        else:
            state.supplier_uncertainty_buffer += 3
            state.delta_sigma += 0.15
            state.risk_points += 2
            state.manual_review_required = True
            self._warn(state, "QUOTE_INCOMPLETE", "high", "Quote completeness is below 0.50.")
            self._explain(state, "quote_completeness_score", score, "+3 supplier_uncertainty_buffer_days", "Quote completeness is below 0.50.")

    def _lead_time_revisions(self, revisions: int | None, state: AdjustmentState) -> None:
        if revisions is None:
            return
        if revisions == 1:
            state.supplier_uncertainty_buffer += 1
            self._explain(state, "lead_time_revision_count", revisions, "+1 supplier_uncertainty_buffer_days", "Supplier revised lead time once.")
        elif revisions >= 2:
            state.supplier_uncertainty_buffer += 3
            state.risk_points += 1
            state.manual_review_required = True
            self._warn(state, "LEAD_TIME_REVISED", "medium", "Supplier revised lead time multiple times.")
            self._explain(state, "lead_time_revision_count", revisions, "+3 supplier_uncertainty_buffer_days", "Supplier revised lead time at least twice.")

    def _upstream_signal(self, signal: float | None, state: AdjustmentState) -> None:
        if signal is None:
            return
        if 0.3 <= signal < 0.7:
            state.supplier_uncertainty_buffer += 2
            self._explain(state, "upstream_confirmation_signal", signal, "+2 supplier_uncertainty_buffer_days", "Upstream confirmation signal is moderate.")
        elif signal >= 0.7:
            state.supplier_uncertainty_buffer += 3
            state.fallback_supplier_required = True
            state.risk_points += 1
            self._warn(state, "UPSTREAM_CONFIRMATION_PENDING", "medium", "Upstream material or production confirmation appears pending.")
            self._explain(state, "upstream_confirmation_signal", signal, "+3 supplier_uncertainty_buffer_days", "Upstream confirmation signal is high.")

    def _supplier_load(self, load: float | None, state: AdjustmentState) -> None:
        if load is None:
            return
        if 0.5 <= load < 0.8:
            state.supplier_uncertainty_buffer += 1
            self._explain(state, "supplier_current_load_signal", load, "+1 supplier_uncertainty_buffer_days", "Supplier load signal is elevated.")
        elif load >= 0.8:
            state.supplier_uncertainty_buffer += 3
            state.risk_points += 1
            state.fallback_supplier_required = True
            self._warn(state, "SUPPLIER_LOAD_HIGH", "medium", "Supplier current load signal is high.")
            self._explain(state, "supplier_current_load_signal", load, "+3 supplier_uncertainty_buffer_days", "Supplier current load signal is high.")

    def _requirement_changes(self, changes: int | None, state: AdjustmentState) -> None:
        if changes is None:
            return
        if changes == 1:
            state.buyer_decision_buffer += 2
            self._explain(state, "requirement_change_count", changes, "+2 buyer_decision_buffer_days", "Buyer changed requirements once.")
        elif changes >= 2:
            days = min(7.0, 3.0 + changes)
            state.buyer_decision_buffer += days
            state.risk_points += 1
            self._warn(state, "BUYER_REQUIREMENT_VOLATILITY", "medium", "Buyer requirements changed multiple times.")
            self._explain(state, "requirement_change_count", changes, f"+{int(days)} buyer_decision_buffer_days", "Buyer changed requirements at least twice.")

    def _buyer_decision_delay(self, score: float | None, state: AdjustmentState) -> None:
        if score is None:
            return
        if 0.3 <= score < 0.7:
            state.buyer_decision_buffer += 2
            self._explain(state, "buyer_decision_delay_score", score, "+2 buyer_decision_buffer_days", "Buyer decision delay score is moderate.")
        elif score >= 0.7:
            state.buyer_decision_buffer += 5
            state.risk_points += 1
            self._warn(state, "BUYER_DECISION_DELAY", "medium", "Buyer decision delay score is high.")
            self._explain(state, "buyer_decision_delay_score", score, "+5 buyer_decision_buffer_days", "Buyer decision delay score is high.")

    def _risk(
        self,
        req: GLTGSimulationRequestV2,
        selected: float,
        p50: float,
        p80: float,
        p90: float,
        state: AdjustmentState,
    ) -> GLTGRiskOutput:
        deadline = req.order.deadline_days
        feasible = None
        if deadline is not None:
            feasible = selected <= deadline
            if selected <= deadline:
                level = "low" if state.risk_points == 0 else "medium"
            elif p50 <= deadline:
                level = "medium_high"
            else:
                level = "high"
        else:
            level = "low" if state.risk_points == 0 else ("medium" if state.risk_points <= 2 else "high")

        fallback_required = state.fallback_supplier_required or level in {"medium_high", "high"}
        manual_review = state.manual_review_required
        if req.constraints.manual_review_policy == "required_if_deadline_tight" and level in {"medium_high", "high"}:
            manual_review = True
        confidence_score = self._confidence(req, state, p50, p90)
        return GLTGRiskOutput(
            deadline_risk_level=level,
            confidence_score=confidence_score,
            fallback_supplier_required=fallback_required,
            manual_review_required=manual_review,
            deadline_feasible=feasible,
            selected_confidence_days=round(selected, 2),
        )

    def _confidence(self, req: GLTGSimulationRequestV2, state: AdjustmentState, p50: float, p90: float) -> float:
        supplier_conf = req.supplier.confidence if req.supplier.confidence is not None else 0.7
        baseline_bonus = 0.08 if req.historical_baseline.sample_size and req.historical_baseline.sample_size >= 30 else 0.0
        width_penalty = min(0.25, max(0.0, (p90 - p50) / max(p50, 1.0) * 0.2))
        behavior_penalty = min(0.25, state.risk_points * 0.06)
        return round(max(0.0, min(1.0, supplier_conf + baseline_bonus - width_penalty - behavior_penalty)), 3)

    @staticmethod
    def _repair_monotonic(p50: float, p80: float, p90: float) -> tuple[float, float, float]:
        p50 = max(float(p50), 0.0)
        p80 = max(float(p80), p50)
        p90 = max(float(p90), p80)
        return p50, p80, p90

    @staticmethod
    def _run_id(req: GLTGSimulationRequestV2) -> str:
        payload = json.dumps(req.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
        return f"GLTG_{digest}"

    @staticmethod
    def _warn(state: AdjustmentState, code: str, severity: str, message: str) -> None:
        if code not in {w.code for w in state.warnings}:
            state.warnings.append(GLTGWarningV2(code=code, severity=severity, message=message))

    @staticmethod
    def _explain(state: AdjustmentState, feature: str, value: Any, adjustment: str, reason: str) -> None:
        state.explanations.append({
            "feature": feature,
            "value": value,
            "adjustment": adjustment,
            "reason": reason,
        })

    @staticmethod
    def _summary(risk: GLTGRiskOutput, baseline_source: str) -> str:
        return (
            f"{risk.selected_confidence_days} days selected from {baseline_source}; "
            f"deadline risk={risk.deadline_risk_level}, "
            f"fallback_required={risk.fallback_supplier_required}, "
            f"manual_review_required={risk.manual_review_required}."
        )


def _transit_days(destination: str | None, logistics_mode: str | None) -> int:
    dest = (destination or "").lower()
    if "air" in (logistics_mode or "").lower():
        for city, days in AIR_TRANSIT_DAYS.items():
            if city in dest:
                return days
        return 4
    for city, days in SEA_TRANSIT_DAYS.items():
        if city in dest:
            return days
    return 20


def _production_days(quantity: int, capacity_per_day: int | None) -> float:
    cap = capacity_per_day or DEFAULT_DAILY_CAPACITY
    effective = max(int(cap * PRODUCTION_EFFICIENCY), 1)
    return float(max(math.ceil(quantity / effective), 1) + 2)


def _baseline_stage_days(
    quantity: int,
    destination: str | None,
    logistics_mode: str | None,
    capacity_per_day: int | None,
) -> dict[str, float]:
    return {
        "material_ready_days": 17.0,
        "production_days": _production_days(quantity, capacity_per_day),
        "qc_days": 6.0,
        "logistics_days": float(10 + _transit_days(destination, logistics_mode)),
    }
