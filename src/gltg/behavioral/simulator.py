"""Deterministic rule-based lead-time engine (demoted to guardrail/fallback).

This is NOT the primary GLTG v2 model. The provider-agnostic LLM-assisted
evaluator (``gltg.evaluator``) is the default. These hard-coded formulas are
retained only as deterministic guardrails / sanity checks / optional fallback,
reached via ``gltg.evaluator.fallback_rules`` when ``GLTG_EVALUATOR_MODE=fallback``
or when a provider fails and ``GLTG_ALLOW_RULE_FALLBACK=true``.
"""

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
    GLTGResponseDelayReasonInference,
    GLTGRiskDecomposition,
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
MATERIAL_STATUS_RISK = {
    "in_stock": 0.05,
    "reserved_stock": 0.10,
    "partial_stock": 0.45,
    "supplier_confirmation_required": 0.65,
    "not_available": 0.90,
    "substitute_material_required": 0.85,
    "unknown": 0.70,
}
TRADER_MODES = {"trader", "broker"}


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


@dataclass
class TradeProcessingCalculation:
    central_shift_days: float = 0.0
    uncertainty_buffer_days: float = 0.0
    risk_decomposition: GLTGRiskDecomposition = field(default_factory=GLTGRiskDecomposition)
    response_delay_reason_inference: GLTGResponseDelayReasonInference = field(
        default_factory=GLTGResponseDelayReasonInference
    )
    execution_control_score: float = 0.0
    upstream_dependency_probability: float = 0.0
    material_availability_risk: float = 0.0
    quote_confidence_score: float = 0.0


class BehavioralLeadTimeSimulator:
    """Composes baseline quantiles with deterministic behavior adjustments."""

    def simulate(self, req: GLTGSimulationRequestV2) -> GLTGSimulationResponseV2:
        base_q, components, baseline_source = self._baseline(req)
        state = self._behavior_adjustments(req)
        trade_calc = self._trade_processing_adjustments(req, components, state)

        shift = state.supplier_response_buffer + state.buyer_decision_buffer + trade_calc.central_shift_days
        uncertainty = state.supplier_uncertainty_buffer + state.risk_buffer + trade_calc.uncertainty_buffer_days
        if self._has_trade_processing_factors(req):
            p50, p80, p90 = self._compose_trade_processing_spread(
                base_q,
                shift,
                trade_calc.risk_decomposition.lead_time_uncertainty_risk,
            )
            composer = "trade_processing_factor_spread"
        elif self._has_distribution(req):
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
            risk_decomposition=trade_calc.risk_decomposition,
            response_delay_reason_inference=trade_calc.response_delay_reason_inference,
            risk=risk,
            explanation_json={
                "summary": self._summary(risk, baseline_source, trade_calc.response_delay_reason_inference),
                "baseline_source": baseline_source,
                "composer": composer,
                "composition_parameters": {
                    "central_shift_days": round(shift, 2),
                    "uncertainty_buffer_days": round(uncertainty, 2),
                    "delta_sigma": round(state.delta_sigma, 4),
                },
                "adjustments": state.explanations,
                "trade_processing_factor_scores": {
                    "material_availability_risk": trade_calc.material_availability_risk,
                    "upstream_dependency_probability": trade_calc.upstream_dependency_probability,
                    "execution_control_score": trade_calc.execution_control_score,
                    "quote_confidence_score": trade_calc.quote_confidence_score,
                },
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

    @staticmethod
    def _compose_trade_processing_spread(
        base_q: GLTGQuantiles,
        central_shift_days: float,
        lead_time_uncertainty_risk: float,
    ) -> tuple[float, float, float]:
        p50 = base_q.p50_days + central_shift_days
        base_spread = max(3.0, base_q.p80_days - base_q.p50_days, (base_q.p90_days - base_q.p50_days) * 0.7)
        p80 = p50 + base_spread * (1 + 0.8 * lead_time_uncertainty_risk)
        p90 = p50 + base_spread * (1 + 1.3 * lead_time_uncertainty_risk)
        return p50, p80, p90

    def _trade_processing_adjustments(
        self,
        req: GLTGSimulationRequestV2,
        components: GLTGComponentBreakdown,
        state: AdjustmentState,
    ) -> TradeProcessingCalculation:
        if not self._has_trade_processing_factors(req):
            return TradeProcessingCalculation()

        f = req.trade_processing_factors
        material_risk = self._material_availability_risk(req)
        upstream_dependency = self._upstream_dependency_probability(req)
        execution_control = self._execution_control_score(req, upstream_dependency)
        response_inference = self._response_delay_reason_inference(req, execution_control, material_risk)
        capacity_risk = self._capacity_queue_risk(f.supplier_execution.capacity_utilization_ratio)
        process_multiplier = self._process_complexity_multiplier(req)
        quality_rework_risk = _clip(_nz(f.processing.rework_probability, 0.0))
        logistics_risk = _clip(
            0.35 * _nz(f.logistics_trade.freight_space_risk, 0.0)
            + 0.25 * _nz(f.logistics_trade.logistics_disruption_score, 0.0)
            + 0.20 * _nz(f.logistics_trade.calendar_disruption_score, 0.0)
            + 0.20 * (1 - _nz(f.logistics_trade.export_doc_readiness_score, 0.85))
        )
        customs_compliance_risk = _clip(
            0.55 * _nz(f.logistics_trade.customs_inspection_probability, 0.0)
            + 0.45 * _nz(f.logistics_trade.trade_compliance_risk, 0.0)
        )
        buyer_delay_risk = _clip(
            0.35 * _nz(f.requirement.requirement_volatility_score, 0.0)
            + 0.30 * _nz(f.requirement.sample_approval_delay_score, 0.0)
            + 0.20 * _nz(f.requirement.payment_delay_risk, 0.0)
            + 0.15 * _nz(req.behavior_features.buyer.buyer_decision_delay_score, 0.0)
        )
        quote_confidence = self._quote_confidence_score(req, execution_control)
        quote_confidence_penalty = _clip(1 - quote_confidence)
        engagement_risk = _clip(
            _first(
                f.behavior.low_engagement_probability,
                response_inference.probabilities.get("low_engagement"),
                0.0,
            )
        )

        risk_decomposition = GLTGRiskDecomposition(
            engagement_risk=round(engagement_risk, 3),
            execution_control_risk=round(_clip(1 - execution_control), 3),
            upstream_dependency_risk=round(upstream_dependency, 3),
            material_availability_risk=round(material_risk, 3),
            capacity_risk=round(capacity_risk, 3),
            process_complexity_risk=round(_clip((process_multiplier - 1) / 1), 3),
            quality_rework_risk=round(quality_rework_risk, 3),
            logistics_risk=round(logistics_risk, 3),
            customs_compliance_risk=round(customs_compliance_risk, 3),
            buyer_delay_risk=round(buyer_delay_risk, 3),
            quote_confidence_penalty=round(quote_confidence_penalty, 3),
        )
        risk_decomposition.lead_time_uncertainty_risk = round(_clip(
            0.18 * material_risk
            + 0.16 * upstream_dependency
            + 0.14 * (1 - execution_control)
            + 0.12 * capacity_risk
            + 0.10 * risk_decomposition.process_complexity_risk
            + 0.10 * quality_rework_risk
            + 0.10 * logistics_risk
            + 0.08 * customs_compliance_risk
            + 0.07 * buyer_delay_risk
            + 0.05 * quote_confidence_penalty
        ), 3)

        self._apply_trade_processing_components(
            req,
            components,
            process_multiplier,
            material_risk,
            capacity_risk,
            risk_decomposition,
        )
        self._apply_trade_processing_warnings(req, state, quote_confidence, response_inference, risk_decomposition)

        central_shift_days = (
            components.requirement_confirmation_days
            + components.material_confirmation_days
            + components.material_procurement_days
            + components.preproduction_days
            + components.capacity_queue_days
            + components.expected_rework_days
            + components.packaging_days
            + components.export_preparation_days
            + components.origin_inland_days
            + components.departure_wait_days
            + components.import_clearance_days
            + components.destination_inland_days
        )
        uncertainty_buffer_days = 4.0 + 10.0 * risk_decomposition.lead_time_uncertainty_risk
        return TradeProcessingCalculation(
            central_shift_days=round(central_shift_days, 2),
            uncertainty_buffer_days=round(uncertainty_buffer_days, 2),
            risk_decomposition=risk_decomposition,
            response_delay_reason_inference=response_inference,
            execution_control_score=round(execution_control, 3),
            upstream_dependency_probability=round(upstream_dependency, 3),
            material_availability_risk=round(material_risk, 3),
            quote_confidence_score=round(quote_confidence, 3),
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

    @staticmethod
    def _has_trade_processing_factors(req: GLTGSimulationRequestV2) -> bool:
        return req.trade_processing_factors.model_dump(exclude_defaults=True, exclude_none=True) != {}

    def _material_availability_risk(self, req: GLTGSimulationRequestV2) -> float:
        material = req.trade_processing_factors.material
        status_risk = MATERIAL_STATUS_RISK.get(material.material_availability_status, MATERIAL_STATUS_RISK["unknown"])
        confidence = _first(material.material_availability_confidence, 0.35)
        return _clip(
            0.25 * status_risk
            + 0.20 * (1 - confidence)
            + 0.20 * _nz(material.raw_material_supplier_confirmation_probability, 0.0)
            + 0.15 * _nz(material.raw_material_lead_time_uncertainty_score, 0.0)
            + 0.10 * _nz(material.substitute_material_probability, 0.0)
            + 0.10 * _nz(material.historical_material_delay_rate, 0.0)
        )

    def _execution_control_score(self, req: GLTGSimulationRequestV2, upstream_dependency: float) -> float:
        factors = req.trade_processing_factors
        supplier = factors.supplier_execution
        material = factors.material
        behavior = factors.behavior
        provided = supplier.execution_control_score
        if provided is not None:
            return _clip(provided)
        quote_completeness = _first(behavior.quote_completeness_score, req.behavior_features.supplier.quote_completeness_score, 0.65)
        on_time = _first(
            req.behavior_features.supplier.historical_on_time_delivery_rate,
            req.historical_baseline.on_time_delivery_rate,
            0.65,
        )
        score = (
            0.35 * _first(supplier.in_house_capability_confidence, 0.45)
            + 0.20 * on_time
            + 0.15 * quote_completeness
            + 0.15 * _first(material.material_availability_confidence, 0.35)
            + 0.15 * (1 - upstream_dependency)
        )
        if supplier.supplier_execution_mode in TRADER_MODES:
            score -= 0.12
        return _clip(score)

    def _upstream_dependency_probability(self, req: GLTGSimulationRequestV2) -> float:
        factors = req.trade_processing_factors
        supplier = factors.supplier_execution
        material = factors.material
        behavior = factors.behavior
        if supplier.upstream_dependency_probability is not None:
            return _clip(supplier.upstream_dependency_probability)
        explicit_upstream = _first(req.behavior_features.supplier.upstream_confirmation_signal, 0.0)
        missing_material_status = 1.0 if behavior.missing_material_status or material.material_availability_status == "unknown" else 0.0
        trader_score = 1.0 if supplier.supplier_execution_mode in TRADER_MODES else 0.0
        response_delay_score = _ratio_score(_first(behavior.supplier_response_delay_ratio, req.behavior_features.supplier.response_delay_ratio, 1.0))
        historical_error_score = _clip(abs(_nz(req.historical_baseline.historical_quoted_vs_actual_error_days, 0.0)) / 10)
        quote_revision_score = _clip(_nz(req.behavior_features.supplier.quote_revision_count, 0.0) / 4)
        return _clip(
            0.25 * explicit_upstream
            + 0.20 * _nz(material.raw_material_supplier_confirmation_probability, 0.0)
            + 0.15 * missing_material_status
            + 0.10 * trader_score
            + 0.10 * _nz(factors.processing.external_subprocess_dependency_score, 0.0)
            + 0.10 * quote_revision_score
            + 0.05 * response_delay_score
            + 0.05 * historical_error_score
        )

    def _response_delay_reason_inference(
        self,
        req: GLTGSimulationRequestV2,
        execution_control: float,
        material_risk: float,
    ) -> GLTGResponseDelayReasonInference:
        f = req.trade_processing_factors
        behavior = f.behavior
        material = f.material
        supplier = f.supplier_execution
        provided = behavior.most_likely_response_delay_reason
        if provided:
            return GLTGResponseDelayReasonInference(
                most_likely_reason=provided,
                confidence=1.0,
                probabilities={provided: 1.0},
            )
        response_delay_score = _ratio_score(_first(behavior.supplier_response_delay_ratio, req.behavior_features.supplier.response_delay_ratio, 1.0))
        missing_material_status = 1.0 if behavior.missing_material_status or material.material_availability_status == "unknown" else 0.0
        incomplete_quote_score = 1 - _first(behavior.quote_completeness_score, req.behavior_features.supplier.quote_completeness_score, 0.65)
        low_relationship_strength_score = 1 - _first(req.behavior_features.pair.relationship_strength_score, 0.6)
        in_house = _first(supplier.in_house_capability_confidence, execution_control)
        complete_quote_score = _first(behavior.quote_completeness_score, req.behavior_features.supplier.quote_completeness_score, 0.65)
        scores = {
            "material_inventory_check": (
                0.35 * _nz(behavior.material_keywords, 0.0)
                + 0.25 * missing_material_status
                + 0.20 * response_delay_score
                + 0.20 * in_house
            ),
            "raw_material_supplier_confirmation": (
                0.40 * _nz(behavior.explicit_material_supplier_signal, 0.0)
                + 0.20 * _nz(material.raw_material_supplier_confirmation_probability, 0.0)
                + 0.15 * missing_material_status
                + 0.15 * response_delay_score
                + 0.10 * _nz(material.historical_material_delay_rate, material_risk)
            ),
            "capacity_check": (
                0.35 * _nz(behavior.capacity_keywords, 0.0)
                + 0.25 * _nz(f.supplier_execution.capacity_utilization_ratio, 0.0)
                + 0.20 * _nz(behavior.production_schedule_keywords, 0.0)
                + 0.20 * in_house
            ),
            "subsupplier_process_confirmation": (
                0.45 * _nz(f.processing.external_subprocess_dependency_score, 0.0)
                + 0.25 * _nz(f.supplier_execution.upstream_dependency_probability, 0.0)
                + 0.20 * response_delay_score
                + 0.10 * missing_material_status
            ),
            "low_engagement": (
                0.30 * response_delay_score
                + 0.20 * incomplete_quote_score
                + 0.20 * (1 - _first(req.behavior_features.supplier.quote_response_rate, 0.75))
                + 0.15 * low_relationship_strength_score
                + 0.15 * _first(behavior.no_clear_reason_signal, 0.0)
            ),
            "careful_quotation": (
                0.30 * complete_quote_score
                + 0.25 * _nz(behavior.detailed_breakdown_signal, 0.0)
                + 0.20 * _nz(behavior.explicit_checking_signal, 0.0)
                + 0.15 * _first(req.behavior_features.supplier.lead_time_confidence_score, 0.65)
                + 0.10 * in_house
            ),
            "timezone_or_holiday": (
                0.50 * _nz(behavior.non_working_time_overlap, 0.0)
                + 0.30 * _nz(behavior.holiday_calendar_match, 0.0)
                + 0.20 * (1 - response_delay_score)
            ),
            "unknown": 0.05,
        }
        exps = {key: math.exp(value) for key, value in scores.items()}
        total = sum(exps.values()) or 1.0
        probabilities = {key: round(value / total, 3) for key, value in exps.items()}
        reason = max(probabilities, key=probabilities.get)
        return GLTGResponseDelayReasonInference(
            most_likely_reason=reason,
            confidence=probabilities[reason],
            probabilities=probabilities,
        )

    def _quote_confidence_score(self, req: GLTGSimulationRequestV2, execution_control: float) -> float:
        f = req.trade_processing_factors
        behavior = f.behavior
        material = f.material
        provided = behavior.quote_confidence_score
        if provided is not None:
            score = provided
        else:
            quote_completeness = _first(behavior.quote_completeness_score, req.behavior_features.supplier.quote_completeness_score, 0.65)
            material_confidence = _first(material.material_availability_confidence, 0.35)
            lead_time_confidence = _first(req.behavior_features.supplier.lead_time_confidence_score, req.supplier.confidence, 0.65)
            historical_quote_accuracy = _clip(1 - abs(_nz(req.historical_baseline.historical_quoted_vs_actual_error_days, 3.0)) / 14)
            source_evidence = 0.85 if req.source_observation_ids else 0.35
            score = (
                0.25 * quote_completeness
                + 0.20 * material_confidence
                + 0.15 * lead_time_confidence
                + 0.15 * historical_quote_accuracy
                + 0.10 * execution_control
                + 0.10 * source_evidence
                + 0.05 * _nz(behavior.detailed_breakdown_signal, 0.0)
            )
        unsupported_fast_quote = (
            behavior.supplier_response_fast
            and material.material_availability_status in {"unknown", "supplier_confirmation_required"}
            and req.supplier.supplier_stated_lead_time_days is not None
            and material.material_availability_confidence in {None, 0.0}
        ) or behavior.unsupported_precise_leadtime_signal
        if unsupported_fast_quote:
            score -= 0.15
        return _clip(score)

    @staticmethod
    def _capacity_queue_risk(utilization: float | None) -> float:
        if utilization is None or utilization <= 0.70:
            return 0.0
        if utilization <= 0.90:
            return _clip((utilization - 0.70) / 0.20)
        return 1.0

    def _process_complexity_multiplier(self, req: GLTGSimulationRequestV2) -> float:
        f = req.trade_processing_factors
        multiplier = (
            1.0
            + 0.15 * _nz(f.processing.customization_level_score, 0.0)
            + 0.10 * _nz(f.requirement.quality_requirement_level_score, 0.0)
            + 0.10 * _nz(f.requirement.packaging_complexity_score, 0.0)
            + 0.15 * _nz(f.processing.external_subprocess_dependency_score, 0.0)
            + 0.10 * float(f.processing.tooling_required)
            + 0.10 * float(f.processing.color_approval_required)
        )
        return min(2.0, max(1.0, multiplier))

    def _apply_trade_processing_components(
        self,
        req: GLTGSimulationRequestV2,
        components: GLTGComponentBreakdown,
        process_multiplier: float,
        material_risk: float,
        capacity_risk: float,
        risk_decomposition: GLTGRiskDecomposition,
    ) -> None:
        f = req.trade_processing_factors
        components.requirement_confirmation_days = round(
            3.0 * (1 - _first(f.requirement.requirement_completeness_score, 0.85)),
            2,
        )
        material_days = self._material_procurement_days(req)
        components.material_confirmation_days = round(2.0 * material_risk, 2)
        components.material_procurement_days = round(material_days, 2)
        components.preproduction_days = round(
            _nz(f.processing.tooling_days, 0.0)
            + (f.processing.sample_days if f.processing.sample_required and f.processing.sample_days else 0.0)
            + (f.processing.color_approval_days if f.processing.color_approval_required and f.processing.color_approval_days else 0.0)
            + _nz(f.processing.setup_days, 0.0),
            2,
        )
        effective_capacity = self._effective_daily_capacity(req, process_multiplier)
        components.production_days = round(
            _nz(f.processing.setup_days, 0.0)
            + math.ceil(req.order.quantity / max(effective_capacity, 1.0))
            + _nz(f.processing.subprocess_days, 0.0),
            2,
        )
        components.subprocess_days = round(_nz(f.processing.subprocess_days, 0.0), 2)
        components.capacity_queue_days = round(4.0 * capacity_risk / max(_nz(f.supplier_execution.priority_factor, 1.0), 0.1), 2)
        components.qc_days = round(max(components.qc_days, 2.0 + 3.0 * _nz(f.processing.qc_intensity_score, 0.0)), 2)
        components.expected_rework_days = round(
            _nz(f.processing.rework_probability, 0.0) * _nz(f.processing.rework_days_if_triggered, 5.0),
            2,
        )
        components.packaging_days = round(1.0 + 2.0 * _nz(f.requirement.packaging_complexity_score, 0.0), 2)
        components.export_preparation_days = round(1.0 + 2.0 * (1 - _nz(f.logistics_trade.export_doc_readiness_score, 0.85)), 2)
        components.origin_inland_days = round(_nz(f.logistics_trade.origin_inland_days, 1.0), 2)
        departure_frequency = _nz(f.logistics_trade.departure_frequency_days, 7.0)
        components.departure_wait_days = round(
            departure_frequency / 2 + _nz(f.logistics_trade.freight_space_risk, 0.0) * departure_frequency,
            2,
        )
        components.main_freight_days = round(
            _first(f.logistics_trade.route_baseline_days, components.logistics_buffer_days, 0.0),
            2,
        )
        components.import_clearance_days = round(_nz(f.logistics_trade.import_clearance_days, 2.0), 2)
        components.destination_inland_days = round(_nz(f.logistics_trade.destination_inland_days, 2.0), 2)
        components.buyer_decision_buffer_days += round(
            _nz(req.behavior_features.buyer.buyer_decision_delay_score, 0.0) * 5.0
            + _nz(f.requirement.requirement_volatility_score, 0.0) * 4.0
            + _nz(f.requirement.sample_approval_delay_score, 0.0) * _nz(f.processing.sample_days, 3.0)
            + _nz(f.requirement.payment_delay_risk, 0.0) * 3.0,
            2,
        )
        components.risk_buffer_days += round(6.0 * risk_decomposition.lead_time_uncertainty_risk, 2)
        components.base_production_days = round(max(components.base_production_days, components.production_days), 2)
        components.base_procurement_days = round(max(components.base_procurement_days, components.material_procurement_days), 2)
        components.logistics_buffer_days = round(
            max(
                components.logistics_buffer_days,
                components.export_preparation_days
                + components.origin_inland_days
                + components.departure_wait_days
                + components.main_freight_days
                + components.import_clearance_days
                + components.destination_inland_days,
            ),
            2,
        )

    def _material_procurement_days(self, req: GLTGSimulationRequestV2) -> float:
        material = req.trade_processing_factors.material
        status = material.material_availability_status
        if status == "in_stock":
            return 0.0
        if status == "reserved_stock":
            return 1.0
        if status == "partial_stock":
            shortage_ratio = 1 - min(_nz(material.stock_coverage_ratio, 0.5), 1.0)
            return max(1.0, _nz(material.raw_material_lead_time_estimate_days, 7.0) * shortage_ratio)
        if status == "supplier_confirmation_required":
            return _nz(material.raw_material_lead_time_estimate_days, 7.0)
        if status == "substitute_material_required":
            return 3.0 + _nz(material.raw_material_lead_time_estimate_days, 7.0)
        if status == "not_available":
            return max(10.0, _nz(material.raw_material_lead_time_estimate_days, 12.0))
        return 10.0 * (1 + _nz(material.raw_material_lead_time_uncertainty_score, 0.4))

    def _effective_daily_capacity(self, req: GLTGSimulationRequestV2, process_multiplier: float) -> float:
        supplier = req.trade_processing_factors.supplier_execution
        if supplier.effective_daily_capacity:
            return supplier.effective_daily_capacity
        nominal = _first(supplier.nominal_daily_capacity, req.supplier.capacity_per_day, DEFAULT_DAILY_CAPACITY)
        capacity_availability = max(0.0, 1 - _nz(supplier.capacity_utilization_ratio, 0.0))
        priority_factor = _nz(supplier.priority_factor, 1.0)
        yield_rate = _first(req.trade_processing_factors.processing.expected_yield_rate, 0.95)
        return max(1.0, nominal * max(capacity_availability, 0.15) * yield_rate * priority_factor / process_multiplier)

    def _apply_trade_processing_warnings(
        self,
        req: GLTGSimulationRequestV2,
        state: AdjustmentState,
        quote_confidence: float,
        response_inference: GLTGResponseDelayReasonInference,
        risk_decomposition: GLTGRiskDecomposition,
    ) -> None:
        material = req.trade_processing_factors.material
        behavior = req.trade_processing_factors.behavior
        supplier = req.trade_processing_factors.supplier_execution
        if material.material_availability_status in {"unknown", "supplier_confirmation_required", "partial_stock"}:
            self._warn(state, "MATERIAL_AVAILABILITY_UNCERTAIN", "medium", "Material availability is not fully confirmed.")
        if quote_confidence < 0.5:
            state.manual_review_required = True
            self._warn(state, "QUOTE_CONFIDENCE_LOW", "medium", "Quote confidence is low after material and evidence checks.")
        if behavior.supplier_response_fast and material.material_availability_status in {"unknown", "supplier_confirmation_required"}:
            state.manual_review_required = True
            self._warn(state, "UNSUPPORTED_FAST_PRECISE_QUOTE", "medium", "Fast supplier response lacks material evidence for the stated lead time.")
        if supplier.supplier_execution_mode in TRADER_MODES and risk_decomposition.upstream_dependency_risk >= 0.6:
            state.fallback_supplier_required = True
            self._warn(state, "TRADER_UPSTREAM_DEPENDENCY_HIGH", "medium", "Trader or broker path has high upstream dependency.")
        if response_inference.most_likely_reason == "raw_material_supplier_confirmation":
            self._explain(
                state,
                "supplier_response_delay_reason",
                response_inference.most_likely_reason,
                "P50 moderate material confirmation shift, P80/P90 material uncertainty widening",
                "Slow response is classified as material supplier confirmation rather than low engagement.",
            )
        if risk_decomposition.lead_time_uncertainty_risk >= 0.65:
            state.fallback_supplier_required = True

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
            material_procurement_days=round(procurement, 2),
            production_days=round(production, 2),
            qc_days=round(qc, 2),
            logistics_buffer_days=round(logistics, 2),
            main_freight_days=round(logistics, 2),
        )

    def _behavior_adjustments(self, req: GLTGSimulationRequestV2) -> AdjustmentState:
        s = req.behavior_features.supplier
        b = req.behavior_features.buyer
        state = AdjustmentState()
        if self._has_trade_processing_factors(req):
            trade = req.trade_processing_factors
            response_delay_ratio = trade.behavior.supplier_response_delay_ratio
            business_hours_delay_ratio = trade.behavior.business_hours_delay_ratio
            quote_completeness_score = trade.behavior.quote_completeness_score
            lead_time_revision_count = None
            upstream_signal = trade.supplier_execution.upstream_dependency_probability
            supplier_load = trade.supplier_execution.capacity_utilization_ratio
            requirement_changes = None
            buyer_decision_delay_score = None
        else:
            response_delay_ratio = s.response_delay_ratio
            business_hours_delay_ratio = s.business_hours_delay_ratio
            quote_completeness_score = s.quote_completeness_score
            lead_time_revision_count = s.lead_time_revision_count
            upstream_signal = s.upstream_confirmation_signal
            supplier_load = s.supplier_current_load_signal
            requirement_changes = b.requirement_change_count
            buyer_decision_delay_score = b.buyer_decision_delay_score

        self._supplier_response_delay(response_delay_ratio, state)
        self._business_hours_delay(business_hours_delay_ratio, state)
        self._quote_completeness(quote_completeness_score, state)
        self._lead_time_revisions(lead_time_revision_count, state)
        self._upstream_signal(upstream_signal, state)
        self._supplier_load(supplier_load, state)
        self._requirement_changes(requirement_changes, state)
        self._buyer_decision_delay(buyer_decision_delay_score, state)

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
    def _summary(
        risk: GLTGRiskOutput,
        baseline_source: str,
        response_inference: GLTGResponseDelayReasonInference,
    ) -> str:
        summary = (
            f"{risk.selected_confidence_days} days selected from {baseline_source}; "
            f"deadline risk={risk.deadline_risk_level}, "
            f"fallback_required={risk.fallback_supplier_required}, "
            f"manual_review_required={risk.manual_review_required}."
        )
        if response_inference.most_likely_reason != "unknown":
            reason_label = response_inference.most_likely_reason.replace("_", " ")
            summary += (
                f" Supplier response delay reason is classified as "
                f"{reason_label} "
                f"(confidence={response_inference.confidence})."
            )
        return summary


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


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _nz(value: float | int | None, default: float = 0.0) -> float:
    return float(default if value is None else value)


def _first(*values: float | int | None) -> float:
    for value in values:
        if value is not None:
            return float(value)
    return 0.0


def _ratio_score(ratio: float | None) -> float:
    if ratio is None:
        return 0.0
    if ratio <= 1.0:
        return 0.0
    return _clip((float(ratio) - 1.0) / 4.0)
