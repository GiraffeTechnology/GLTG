"""Deterministic rule engine entry point (the Stage 3 default v2 path).

Runs the :class:`BehavioralLeadTimeSimulator` and projects its output into
the v2 response shape. Reached three ways:

* ``GLTG_EVALUATOR_MODE=deterministic`` (default) — ``evaluation_mode="deterministic"``;
* ``GLTG_EVALUATOR_MODE=fallback`` (deprecated alias) — same engine, labeled
  ``evaluation_mode="fallback"`` for compatibility with pre-Stage-3 callers;
* explicit ``GLTG_EVALUATOR_MODE=llm`` whose provider fails while
  ``GLTG_ALLOW_RULE_FALLBACK=true`` — labeled ``fallback`` with a warning.
"""

from __future__ import annotations

from ..behavioral.schemas import (
    GLTGSimulationResponseV2,
    GLTGWarningV2,
)
from ..behavioral.simulator import BehavioralLeadTimeSimulator
from .config import EvaluatorSettings
from .schemas import ASSESSMENT_SCHEMA_VERSION, GLTGAssessmentInput, GLTGAssessmentPacket

_simulator = BehavioralLeadTimeSimulator()

FALLBACK_PROVIDER = "deterministic_fallback"
DETERMINISTIC_PROVIDER = "deterministic_rules"


def run_fallback(
    req: GLTGAssessmentInput,
    settings: EvaluatorSettings,
    *,
    provider_unavailable: bool = False,
    deprecated_fallback_alias: bool = False,
) -> GLTGSimulationResponseV2:
    """Run the deterministic simulator and project it to a v2 response."""

    response = _simulator.simulate(req)

    is_primary = not provider_unavailable and not deprecated_fallback_alias
    packet = _packet_from_response(
        req, response, mode="deterministic" if is_primary else "fallback"
    )
    response.assessment_schema_version = ASSESSMENT_SCHEMA_VERSION
    response.model_provider = DETERMINISTIC_PROVIDER if is_primary else FALLBACK_PROVIDER
    response.model_name = response.rule_version
    response.evaluation_mode = "deterministic" if is_primary else "fallback"
    response.assessment_packet = packet.model_dump()
    response.manual_review_required = response.risk.manual_review_required
    response.fallback_supplier_required = response.risk.fallback_supplier_required

    if provider_unavailable:
        response.warnings.append(
            GLTGWarningV2(
                code="LLM_PROVIDER_UNAVAILABLE_RULE_FALLBACK_USED",
                severity="medium",
                message="LLM provider unavailable; deterministic rule fallback used.",
            )
        )
    elif deprecated_fallback_alias:
        response.warnings.append(
            GLTGWarningV2(
                code="RULE_FALLBACK_MODE",
                severity="low",
                message="GLTG is running in deterministic fallback mode, not LLM-assisted mode.",
            )
        )
    return response


def _packet_from_response(
    req: GLTGAssessmentInput, response: GLTGSimulationResponseV2, mode: str = "fallback"
) -> GLTGAssessmentPacket:
    material = req.trade_processing_factors.material
    evidence = list(req.source_observation_ids)
    provider = DETERMINISTIC_PROVIDER if mode == "deterministic" else FALLBACK_PROVIDER
    packet = GLTGAssessmentPacket(
        model_provider=provider,
        model_name=response.rule_version,
        evaluation_mode=mode,
        case_context=req.case_context.model_dump(),
        evidence_refs=evidence,
    )
    packet.material_availability_assessment.material_availability_status = (
        material.material_availability_status
    )
    packet.material_availability_assessment.status = (
        "inferred" if material.material_availability_status != "unknown" else "unknown"
    )
    packet.material_availability_assessment.evidence_refs = evidence

    lt = packet.lead_time_risk_assessment
    lt.p50_days = response.quantiles.p50_days
    lt.p80_days = response.quantiles.p80_days
    lt.p90_days = response.quantiles.p90_days
    lt.deadline_risk_level = response.risk.deadline_risk_level  # type: ignore[assignment]
    lt.risk_decomposition = response.risk_decomposition
    lt.evidence_refs = evidence
    lt.reasoning_summary = "Deterministic rule-based fallback estimate."

    delay = response.response_delay_reason_inference
    packet.response_delay_reason_assessment.most_likely_reason = delay.most_likely_reason
    packet.response_delay_reason_assessment.confidence = delay.confidence
    packet.response_delay_reason_assessment.probabilities = delay.probabilities

    packet.manual_review.required = response.risk.manual_review_required
    packet.fallback_supplier.required = response.risk.fallback_supplier_required
    packet.audit.model_provider = provider
    packet.audit.model_name = response.rule_version
    packet.audit.evaluation_mode = mode
    return packet


__all__ = ["run_fallback", "FALLBACK_PROVIDER"]
