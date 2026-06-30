"""Deterministic guardrails for LLM-produced assessments.

Guardrails are NOT the primary GLTG model. They run *after* the LLM evaluator to
constrain its output: quantile normalization, and the business invariants from
the PRD (fast-unsupported-quote, slow-material-confirmation, deadline
consistency). They can downgrade, widen, or flag -- they never invent a richer
model than the evidence supports.
"""

from __future__ import annotations

from ..behavioral.schemas import GLTGWarningV2
from .schemas import GLTGAssessmentInput, GLTGAssessmentPacket

MIN_SPREAD = 1.0
HIGH_UPSTREAM_DEPENDENCY = 0.6
WIDEN_MATERIAL_STATUSES = {"unknown", "supplier_confirmation_required", "not_available"}


def normalize_quantiles(packet: GLTGAssessmentPacket, req: GLTGAssessmentInput) -> list[str]:
    """Enforce P50<=P80<=P90 (positive) and widen tails for weak evidence.

    Returns a list of human-readable repair notes (empty if nothing changed).
    The LLM may recommend P50/P80/P90, but GLTG owns normalization.
    """

    lt = packet.lead_time_risk_assessment
    notes: list[str] = []

    p50 = max(float(lt.p50_days), 1.0)
    p80 = float(lt.p80_days)
    p90 = float(lt.p90_days)

    # P50 should not sit below a confirmed supplier-stated lead time unless the
    # packet explicitly justifies it with evidence.
    stated = req.supplier.supplier_stated_lead_time_days
    if (
        stated
        and p50 < stated
        and packet.supplier_execution_assessment.status == "confirmed"
        and not lt.reasoning_summary
    ):
        notes.append(f"raised P50 to confirmed stated lead time ({stated}d)")
        p50 = float(stated)

    material_status = packet.material_availability_assessment.material_availability_status
    upstream = float(lt.risk_decomposition.upstream_dependency_risk or 0.0)
    quote_low = packet.quote_confidence_assessment.quote_confidence_level in {"low", "unknown"}

    widen = 0.0
    if material_status in WIDEN_MATERIAL_STATUSES:
        widen += 3.0
        notes.append("widened P80/P90 tail for uncertain material availability")
    if upstream >= HIGH_UPSTREAM_DEPENDENCY:
        widen += 3.0
        notes.append("widened P80/P90 tail for high upstream dependency")
    if quote_low:
        widen += 2.0
        notes.append("widened tail for low quote confidence")

    if p80 < p50 + MIN_SPREAD:
        p80 = p50 + MIN_SPREAD
        notes.append("repaired P80 < P50")
    if p90 < p80 + MIN_SPREAD:
        p90 = p80 + MIN_SPREAD
        notes.append("repaired P90 < P80")

    # Apply tail widening only to P80/P90, not to the central estimate.
    if widen:
        p80 += widen * 0.6
        p90 += widen

    lt.p50_days = round(p50, 2)
    lt.p80_days = round(max(p80, p50 + MIN_SPREAD), 2)
    lt.p90_days = round(max(p90, lt.p80_days + MIN_SPREAD), 2)
    return notes


def apply_business_guardrails(
    packet: GLTGAssessmentPacket, req: GLTGAssessmentInput
) -> list[GLTGWarningV2]:
    """Apply PRD business invariants. Returns warnings; mutates the packet."""

    warnings: list[GLTGWarningV2] = []
    behavior = req.trade_processing_factors.behavior
    material = packet.material_availability_assessment
    quote = packet.quote_confidence_assessment

    material_unsupported = (
        material.material_availability_status in {"unknown", "supplier_confirmation_required"}
        and not material.evidence_refs
    )

    # Fast response + precise lead time + no material evidence -> manual review
    # and/or quote-confidence penalty.
    fast_unsupported = (
        behavior.supplier_response_fast or behavior.unsupported_precise_leadtime_signal
    ) and material_unsupported
    if fast_unsupported:
        if quote.confidence_score > 0.5:
            quote.confidence_score = round(min(quote.confidence_score, 0.45), 3)
            quote.quote_confidence_level = "low"
        quote.unsupported_claims = list(
            {*quote.unsupported_claims, "precise_lead_time_without_material_evidence"}
        )
        _require_manual_review(packet, "fast precise quote lacks material evidence")
        warnings.append(
            GLTGWarningV2(
                code="UNSUPPORTED_FAST_PRECISE_QUOTE",
                severity="medium",
                message="Fast supplier response lacks material evidence for the stated lead time.",
            )
        )

    # Slow response + material-supplier evidence must NOT become automatic low
    # engagement.
    delay = packet.response_delay_reason_assessment
    has_material_signal = (
        (behavior.explicit_material_supplier_signal or 0) >= 0.5
        or (behavior.material_keywords or 0) >= 0.5
        or material.material_availability_status == "supplier_confirmation_required"
    )
    if delay.most_likely_reason == "low_engagement" and has_material_signal:
        delay.most_likely_reason = "raw_material_supplier_confirmation"
        delay.status = "inferred"
        delay.reasoning_summary = (
            "Reclassified from low_engagement: material-supplier confirmation "
            "evidence is present despite the slow response."
        )
        warnings.append(
            GLTGWarningV2(
                code="SLOW_RESPONSE_NOT_LOW_ENGAGEMENT",
                severity="low",
                message="Slow response with material evidence reclassified away from low engagement.",
            )
        )

    # Deadline consistency: a hard target that P80 exceeds cannot be low risk.
    deadline = req.order.deadline_days
    lt = packet.lead_time_risk_assessment
    if deadline is not None and lt.p80_days > deadline and lt.deadline_risk_level == "low":
        lt.deadline_risk_level = "medium_high" if lt.p50_days <= deadline else "high"
        warnings.append(
            GLTGWarningV2(
                code="DEADLINE_RISK_INCONSISTENT",
                severity="medium",
                message="P80 exceeds the target deadline; deadline risk raised from low.",
            )
        )

    return warnings


def _require_manual_review(packet: GLTGAssessmentPacket, reason: str) -> None:
    packet.manual_review.required = True
    if reason not in packet.manual_review.reasons:
        packet.manual_review.reasons.append(reason)


__all__ = ["normalize_quantiles", "apply_business_guardrails", "MIN_SPREAD"]
