"""Helpers to build and project GLTG assessment packets into v2 responses."""

from __future__ import annotations

import hashlib
import json

from ..behavioral.schemas import (
    GLTGQuantiles,
    GLTGResponseDelayReasonInference,
    GLTGRiskOutput,
    GLTGSimulationResponseV2,
    GLTGWarningV2,
)
from .config import EvaluatorSettings
from .schemas import (
    ASSESSMENT_SCHEMA_VERSION,
    GLTGAssessmentInput,
    GLTGAssessmentPacket,
)


def run_id(req: GLTGAssessmentInput) -> str:
    payload = json.dumps(req.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"GLTG_{digest}"


def project_to_response(
    req: GLTGAssessmentInput,
    packet: GLTGAssessmentPacket,
    settings: EvaluatorSettings,
    warnings: list[GLTGWarningV2],
) -> GLTGSimulationResponseV2:
    """Project a validated assessment packet into the GLTG v2 response shape."""

    lt = packet.lead_time_risk_assessment
    quantiles = GLTGQuantiles(
        p50_days=round(lt.p50_days, 2),
        p80_days=round(lt.p80_days, 2),
        p90_days=round(lt.p90_days, 2),
    )
    selected = {
        "P50": quantiles.p50_days,
        "P80": quantiles.p80_days,
        "P90": quantiles.p90_days,
    }[req.constraints.lead_time_confidence]

    deadline = req.order.deadline_days
    deadline_feasible = None if deadline is None else selected <= deadline

    manual_review_required = packet.manual_review.required
    fallback_required = packet.fallback_supplier.required or lt.deadline_risk_level in {
        "medium_high",
        "high",
    }
    if req.constraints.manual_review_policy == "required_if_deadline_tight" and lt.deadline_risk_level in {
        "medium_high",
        "high",
    }:
        manual_review_required = True

    risk = GLTGRiskOutput(
        deadline_risk_level=lt.deadline_risk_level,
        confidence_score=packet.quote_confidence_assessment.confidence_score,
        fallback_supplier_required=fallback_required,
        manual_review_required=manual_review_required,
        deadline_feasible=deadline_feasible,
        selected_confidence_days=round(selected, 2),
    )

    delay = packet.response_delay_reason_assessment
    response_delay = GLTGResponseDelayReasonInference(
        most_likely_reason=delay.most_likely_reason,
        confidence=delay.confidence,
        probabilities=delay.probabilities,
    )

    if not req.source_observation_ids:
        warnings = [*warnings, GLTGWarningV2(
            code="MISSING_SOURCE_OBSERVATIONS",
            severity="low",
            message="No source_observation_ids were provided; lineage is incomplete.",
        )]
    warnings = [*warnings, GLTGWarningV2(
        code="PERSISTENCE_NOT_CONFIGURED",
        severity="low",
        message="GLTG run id is generated, but giraffe-db persistence is not configured in this service build.",
    )]

    explanation = {
        "summary": _summary(packet, settings),
        "evidence_refs": packet.evidence_refs,
        "missing_information": packet.missing_information,
        "follow_up_questions": packet.follow_up_questions,
        "source_observation_ids": list(req.source_observation_ids),
    }

    return GLTGSimulationResponseV2(
        ok=True,
        gltg_run_id=run_id(req),
        assessment_schema_version=packet.assessment_schema_version or ASSESSMENT_SCHEMA_VERSION,
        model_provider=packet.model_provider,
        model_name=packet.model_name,
        evaluation_mode=packet.evaluation_mode,
        quantiles=quantiles,
        risk_decomposition=lt.risk_decomposition,
        response_delay_reason_inference=response_delay,
        risk=risk,
        assessment_packet=packet.model_dump(),
        manual_review_required=manual_review_required,
        fallback_supplier_required=fallback_required,
        explanation_json=explanation,
        warnings=warnings,
    )


def manual_review_packet(
    req: GLTGAssessmentInput,
    settings: EvaluatorSettings,
    reason: str,
    *,
    evaluation_mode: str = "llm",
) -> GLTGAssessmentPacket:
    """Build a conservative manual-review packet when the evaluator is unavailable.

    Quantiles echo whatever baseline / stated lead time exists (input carry-over,
    not an invented model result); manual review is required.
    """

    baseline = req.historical_baseline
    stated = req.supplier.supplier_stated_lead_time_days
    p50 = float(baseline.baseline_p50_days or stated or 0) or 1.0
    p80 = float(baseline.baseline_p80_days or 0) or p50 * 1.25
    p90 = float(baseline.baseline_p90_days or 0) or p50 * 1.5

    packet = GLTGAssessmentPacket(
        model_provider=settings.provider,
        model_name=settings.model,
        evaluation_mode=evaluation_mode,
        case_context=req.case_context.model_dump(),
    )
    packet.lead_time_risk_assessment.p50_days = round(p50, 2)
    packet.lead_time_risk_assessment.p80_days = round(p80, 2)
    packet.lead_time_risk_assessment.p90_days = round(p90, 2)
    packet.lead_time_risk_assessment.deadline_risk_level = "unknown"
    packet.lead_time_risk_assessment.reasoning_summary = (
        "Evaluator unavailable; quantiles carried over from input baseline pending manual review."
    )
    packet.manual_review.required = True
    packet.manual_review.reasons.append(reason)
    packet.missing_information.append("llm_assessment")
    packet.evidence_refs = list(req.source_observation_ids)
    packet.lead_time_risk_assessment.evidence_refs = list(req.source_observation_ids)
    packet.audit.model_provider = settings.provider
    packet.audit.model_name = settings.model
    packet.audit.evaluation_mode = evaluation_mode
    return packet


def _summary(packet: GLTGAssessmentPacket, settings: EvaluatorSettings) -> str:
    lt = packet.lead_time_risk_assessment
    summary = (
        f"GLTG {packet.evaluation_mode} assessment via {packet.model_provider}/{packet.model_name}: "
        f"P50={lt.p50_days}d, P80={lt.p80_days}d, P90={lt.p90_days}d, "
        f"deadline risk={lt.deadline_risk_level}."
    )
    reason = packet.response_delay_reason_assessment.most_likely_reason
    if reason != "unknown":
        summary += f" Response delay reason classified as {reason.replace('_', ' ')}."
    if packet.manual_review.required:
        summary += " Manual review required."
    return summary


__all__ = ["project_to_response", "manual_review_packet", "run_id"]
