"""Structured GLTG Assessment Packet schema (``gltg-assessment-v1``).

The assessment packet is the *primary output* of the LLM-assisted evaluator.
The LLM evaluates trade context; GLTG validates, normalizes, constrains, and
packages the result into this schema. Nothing here is provider-specific.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..behavioral.schemas import GLTGRiskDecomposition, GLTGSimulationRequestV2

ASSESSMENT_SCHEMA_VERSION = "gltg-assessment-v1"

# Every material conclusion must be classified with one of these statuses.
AssessmentStatus = Literal["confirmed", "inferred", "unknown", "needs_confirmation"]

ExecutionMode = Literal[
    "in_house_manufacturer",
    "partial_outsource",
    "trader_or_broker",
    "assembly_only",
    "material_dependent_manufacturer",
    "unknown",
]

MaterialAvailabilityStatus = Literal[
    "in_stock",
    "reserved_stock",
    "partial_stock",
    "supplier_confirmation_required",
    "not_available",
    "substitute_material_required",
    "unknown",
]

ResponseDelayReason = Literal[
    "material_inventory_check",
    "raw_material_supplier_confirmation",
    "capacity_check",
    "subsupplier_process_confirmation",
    "low_engagement",
    "careful_quotation",
    "timezone_or_holiday",
    "unknown",
]

QuoteConfidenceLevel = Literal["low", "medium", "high", "unknown"]
DeadlineRiskLevel = Literal["low", "medium", "medium_high", "high", "unknown"]

# Evidence references must point at input records, not free text. These are the
# allowed logical record types (see GLTG_ASSESSMENT_PACKET_SCHEMA.md).
ALLOWED_EVIDENCE_REF_TYPES = (
    "communication_event_id",
    "behavior_observation_id",
    "supplier_quote_id",
    "supplier_quote_line_item_id",
    "rfq_id",
    "rfq_line_item_id",
    "procurement_case_id",
    "supplier_behavior_feature_snapshot_id",
    "buyer_behavior_feature_snapshot_id",
    "buyer_supplier_behavior_metric_id",
    "operator_confirmed_requirement_id",
    "manual_input_id",
)

# An evidence ref is the record id (string). Providers/tests may emit either a
# bare id string or an object; the validator/normalizer coerces to a list[str].
EvidenceRef = str


class SupplierExecutionAssessment(BaseModel):
    execution_mode: ExecutionMode = "unknown"
    status: AssessmentStatus = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    reasoning_summary: str = ""
    alternative_modes: list[ExecutionMode] = Field(default_factory=list)


class MaterialAvailabilityAssessment(BaseModel):
    material_availability_status: MaterialAvailabilityStatus = "unknown"
    status: AssessmentStatus = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    stock_coverage_ratio: float | None = Field(default=None, ge=0.0)
    raw_material_supplier_confirmation_required: bool | None = None
    raw_material_lead_time_estimate_days: float | None = Field(default=None, ge=0.0)
    material_lock_required: bool | None = None
    material_lock_validity_days: float | None = Field(default=None, ge=0.0)
    substitute_material_required: bool | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    reasoning_summary: str = ""


class ResponseDelayReasonAssessment(BaseModel):
    most_likely_reason: ResponseDelayReason = "unknown"
    status: AssessmentStatus = "inferred"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    probabilities: dict[str, float] = Field(default_factory=dict)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    reasoning_summary: str = ""


class QuoteConfidenceAssessment(BaseModel):
    quote_confidence_level: QuoteConfidenceLevel = "unknown"
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    status: AssessmentStatus = "unknown"
    complete_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    reasoning_summary: str = ""


class LeadTimeRiskAssessment(BaseModel):
    p50_days: float = 0.0
    p80_days: float = 0.0
    p90_days: float = 0.0
    deadline_risk_level: DeadlineRiskLevel = "unknown"
    main_risk_drivers: list[str] = Field(default_factory=list)
    p50_drivers: list[str] = Field(default_factory=list)
    p80_p90_tail_drivers: list[str] = Field(default_factory=list)
    risk_decomposition: GLTGRiskDecomposition = Field(default_factory=GLTGRiskDecomposition)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    reasoning_summary: str = ""


class ManualReview(BaseModel):
    required: bool = False
    reasons: list[str] = Field(default_factory=list)


class FallbackSupplier(BaseModel):
    required: bool = False
    reasons: list[str] = Field(default_factory=list)


class AssessmentAudit(BaseModel):
    model_provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    evaluation_mode: str | None = None
    repaired: bool = False
    repair_notes: list[str] = Field(default_factory=list)


class GLTGAssessmentPacket(BaseModel):
    """Structured, evidence-linked assessment produced per evaluation."""

    assessment_schema_version: str = ASSESSMENT_SCHEMA_VERSION
    model_provider: str = "qwen"
    model_name: str = "qwen3.5"
    model_version: str | None = None
    evaluation_mode: str = "llm"
    case_context: dict[str, Any] = Field(default_factory=dict)
    supplier_execution_assessment: SupplierExecutionAssessment = Field(
        default_factory=SupplierExecutionAssessment
    )
    material_availability_assessment: MaterialAvailabilityAssessment = Field(
        default_factory=MaterialAvailabilityAssessment
    )
    response_delay_reason_assessment: ResponseDelayReasonAssessment = Field(
        default_factory=ResponseDelayReasonAssessment
    )
    quote_confidence_assessment: QuoteConfidenceAssessment = Field(
        default_factory=QuoteConfidenceAssessment
    )
    lead_time_risk_assessment: LeadTimeRiskAssessment = Field(
        default_factory=LeadTimeRiskAssessment
    )
    trade_processing_factor_assessments: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    manual_review: ManualReview = Field(default_factory=ManualReview)
    fallback_supplier: FallbackSupplier = Field(default_factory=FallbackSupplier)
    pricing_implications: dict[str, Any] = Field(default_factory=dict)
    audit: AssessmentAudit = Field(default_factory=AssessmentAudit)


# The evaluator input is the existing v2 simulation request: products send
# observed facts and feature snapshots; GLTG owns the assessment.
GLTGAssessmentInput = GLTGSimulationRequestV2


__all__ = [
    "ASSESSMENT_SCHEMA_VERSION",
    "ALLOWED_EVIDENCE_REF_TYPES",
    "AssessmentStatus",
    "GLTGAssessmentInput",
    "GLTGAssessmentPacket",
    "SupplierExecutionAssessment",
    "MaterialAvailabilityAssessment",
    "ResponseDelayReasonAssessment",
    "QuoteConfidenceAssessment",
    "LeadTimeRiskAssessment",
    "ManualReview",
    "FallbackSupplier",
    "AssessmentAudit",
]
