"""Validator / guardrail layer for LLM-produced assessment packets.

Runs after every provider result. Enforces schema validity, evidence rules,
numeric bounds, quantile monotonicity/normalization, and the PRD business
invariants. If a packet cannot be parsed at all, the orchestrator decides
between a repair pass and a manual-review assessment -- the validator only ever
*downgrades* or *repairs*, it never upgrades a conclusion.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import ValidationError

from ..behavioral.schemas import GLTGWarningV2
from .guardrails import apply_business_guardrails, normalize_quantiles
from .schemas import GLTGAssessmentInput, GLTGAssessmentPacket

HIGH_CONFIDENCE = 0.8
PROBABILITY_SUM_TOLERANCE = 0.05


class PacketParseError(Exception):
    """Raised when raw provider output cannot be parsed into a packet."""


def parse_packet(raw: dict) -> GLTGAssessmentPacket:
    """Parse a normalized provider dict into a typed packet (may raise)."""

    try:
        return GLTGAssessmentPacket.model_validate(raw)
    except ValidationError as exc:
        raise PacketParseError(str(exc)) from exc


@dataclass
class ValidationResult:
    packet: GLTGAssessmentPacket
    warnings: list[GLTGWarningV2] = field(default_factory=list)
    repair_notes: list[str] = field(default_factory=list)


def validate_and_repair(
    packet: GLTGAssessmentPacket, req: GLTGAssessmentInput
) -> ValidationResult:
    result = ValidationResult(packet=packet)

    _enforce_evidence_rules(packet, result)
    _clip_risk_values(packet)
    _normalize_probabilities(packet, result)

    result.repair_notes.extend(normalize_quantiles(packet, req))
    result.warnings.extend(apply_business_guardrails(packet, req))

    if result.repair_notes:
        packet.audit.repaired = True
        packet.audit.repair_notes = list(result.repair_notes)

    return result


def _enforce_evidence_rules(packet: GLTGAssessmentPacket, result: ValidationResult) -> None:
    # (status, confidence, evidence) carriers across the packet.
    se = packet.supplier_execution_assessment
    ma = packet.material_availability_assessment
    rd = packet.response_delay_reason_assessment

    for label, node in (("supplier_execution", se), ("material_availability", ma), ("response_delay", rd)):
        if node.status == "confirmed" and not node.evidence_refs:
            node.status = "needs_confirmation"
            result.warnings.append(
                GLTGWarningV2(
                    code="CONFIRMED_WITHOUT_EVIDENCE_DOWNGRADED",
                    severity="medium",
                    message=f"{label}: confirmed status without evidence_refs downgraded to needs_confirmation.",
                )
            )
        if node.confidence >= HIGH_CONFIDENCE and not node.evidence_refs:
            node.confidence = 0.5
            result.warnings.append(
                GLTGWarningV2(
                    code="HIGH_CONFIDENCE_WITHOUT_EVIDENCE_DOWNGRADED",
                    severity="medium",
                    message=f"{label}: high confidence without evidence_refs downgraded.",
                )
            )

    # Quote confidence carries its own score / level fields.
    qc = packet.quote_confidence_assessment
    if qc.status == "confirmed" and not qc.evidence_refs:
        qc.status = "needs_confirmation"
        result.warnings.append(
            GLTGWarningV2(
                code="CONFIRMED_WITHOUT_EVIDENCE_DOWNGRADED",
                severity="medium",
                message="quote_confidence: confirmed status without evidence_refs downgraded.",
            )
        )
    if (qc.confidence_score >= HIGH_CONFIDENCE or qc.quote_confidence_level == "high") and not qc.evidence_refs:
        qc.confidence_score = min(qc.confidence_score, 0.5)
        qc.quote_confidence_level = "medium" if qc.confidence_score >= 0.4 else "low"
        result.warnings.append(
            GLTGWarningV2(
                code="HIGH_CONFIDENCE_WITHOUT_EVIDENCE_DOWNGRADED",
                severity="medium",
                message="quote_confidence: high confidence without evidence_refs downgraded.",
            )
        )

    # "unknown cannot become confirmed": a confirmed status on an unknown value
    # is contradictory.
    if ma.material_availability_status == "unknown" and ma.status == "confirmed":
        ma.status = "needs_confirmation"
        result.warnings.append(
            GLTGWarningV2(
                code="UNKNOWN_MATERIAL_CANNOT_BE_CONFIRMED",
                severity="medium",
                message="material_availability: unknown status cannot be confirmed.",
            )
        )
    if se.execution_mode == "unknown" and se.status == "confirmed":
        se.status = "needs_confirmation"
        result.warnings.append(
            GLTGWarningV2(
                code="UNKNOWN_EXECUTION_CANNOT_BE_CONFIRMED",
                severity="low",
                message="supplier_execution: unknown mode cannot be confirmed.",
            )
        )


def _clip_risk_values(packet: GLTGAssessmentPacket) -> None:
    rd = packet.lead_time_risk_assessment.risk_decomposition
    for name, value in rd.model_dump().items():
        setattr(rd, name, max(0.0, min(1.0, float(value))))


def _normalize_probabilities(packet: GLTGAssessmentPacket, result: ValidationResult) -> None:
    probs = packet.response_delay_reason_assessment.probabilities
    if not probs:
        return
    clipped = {k: max(0.0, min(1.0, float(v))) for k, v in probs.items()}
    total = sum(clipped.values())
    if total <= 0:
        packet.response_delay_reason_assessment.probabilities = clipped
        return
    if abs(total - 1.0) > PROBABILITY_SUM_TOLERANCE:
        clipped = {k: round(v / total, 4) for k, v in clipped.items()}
        result.warnings.append(
            GLTGWarningV2(
                code="RESPONSE_DELAY_PROBABILITIES_RENORMALIZED",
                severity="low",
                message="Response-delay-reason probabilities did not sum to ~1.0 and were renormalized.",
            )
        )
    packet.response_delay_reason_assessment.probabilities = clipped


__all__ = ["validate_and_repair", "parse_packet", "PacketParseError", "ValidationResult"]
