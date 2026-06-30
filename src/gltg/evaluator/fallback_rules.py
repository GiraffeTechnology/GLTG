"""Deterministic rule-based fallback (demoted from the primary model).

The hard-coded behavioral formulas are NOT the GLTG product model. They are
retained here as guardrail / fallback logic only, used when:

* ``GLTG_EVALUATOR_MODE=fallback`` (explicitly selected), or
* ``GLTG_EVALUATOR_MODE=llm`` and the provider fails and
  ``GLTG_ALLOW_RULE_FALLBACK=true``.

The fallback wraps the legacy :class:`BehavioralLeadTimeSimulator` and projects
its output into the provider-agnostic v2 response shape with
``evaluation_mode="fallback"``.
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


def run_fallback(
    req: GLTGAssessmentInput,
    settings: EvaluatorSettings,
    *,
    provider_unavailable: bool = False,
) -> GLTGSimulationResponseV2:
    """Run the deterministic simulator and project it to a v2 response."""

    response = _simulator.simulate(req)

    packet = _packet_from_response(req, response)

    response.assessment_schema_version = ASSESSMENT_SCHEMA_VERSION
    response.model_provider = FALLBACK_PROVIDER
    response.model_name = response.rule_version
    response.evaluation_mode = "fallback"
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
    else:
        response.warnings.append(
            GLTGWarningV2(
                code="RULE_FALLBACK_MODE",
                severity="low",
                message="GLTG is running in deterministic fallback mode, not LLM-assisted mode.",
            )
        )
    return response


def _packet_from_response(
    req: GLTGAssessmentInput, response: GLTGSimulationResponseV2
) -> GLTGAssessmentPacket:
    material = req.trade_processing_factors.material
    evidence = list(req.source_observation_ids)
    packet = GLTGAssessmentPacket(
        model_provider=FALLBACK_PROVIDER,
        model_name=response.rule_version,
        evaluation_mode="fallback",
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
    packet.audit.model_provider = FALLBACK_PROVIDER
    packet.audit.model_name = response.rule_version
    packet.audit.evaluation_mode = "fallback"
    return packet


__all__ = ["run_fallback", "FALLBACK_PROVIDER"]
