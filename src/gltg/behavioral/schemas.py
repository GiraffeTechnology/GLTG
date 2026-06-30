"""GLTG v2 behavior-aware lead-time API schemas.

This contract is the standalone service boundary for product repositories.
Products send observed facts and feature snapshots; GLTG owns simulation,
composition, risk flags, and explanations.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


LeadTimeConfidence = Literal["P50", "P80", "P90"]


class GLTGCaseContext(BaseModel):
    procurement_case_id: str | None = None
    rfq_id: str | None = None
    quote_id: str | None = None
    po_id: str | None = None
    buyer_id: str | None = None
    supplier_id: str | None = None


class GLTGOrderInputV2(BaseModel):
    product_category_id: str | None = None
    product_id: str | None = None
    product_type: str | None = "apparel"
    product_name: str | None = None
    quantity: int = Field(..., ge=0)
    quantity_unit: str | None = "pcs"
    material: str | None = None
    process_complexity: str | None = None
    customization_level: str | None = None
    destination: str | None = None
    logistics_mode: str | None = None
    deadline_days: int | None = Field(default=None, ge=0)
    target_delivery_date: str | None = None
    quality_requirement_level: str | None = None
    packaging_requirement_level: str | None = None


class GLTGSupplierInputV2(BaseModel):
    supplier_id: str | None = None
    name: str | None = None
    capacity_per_day: int | None = Field(default=None, ge=0)
    material_ready_days: float | None = Field(default=None, ge=0)
    production_days: float | None = Field(default=None, ge=0)
    qc_days: float | None = Field(default=None, ge=0)
    logistics_days: float | None = Field(default=None, ge=0)
    supplier_stated_lead_time_days: float | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class GLTGHistoricalBaseline(BaseModel):
    baseline_source: str | None = None
    sample_size: int | None = Field(default=None, ge=0)
    baseline_p50_days: float | None = Field(default=None, ge=0)
    baseline_p80_days: float | None = Field(default=None, ge=0)
    baseline_p90_days: float | None = Field(default=None, ge=0)
    historical_quoted_vs_actual_error_days: float | None = None
    on_time_delivery_rate: float | None = Field(default=None, ge=0.0, le=1.0)


class GLTGSupplierBehaviorFeatures(BaseModel):
    response_delay_ratio: float | None = Field(default=None, ge=0)
    business_hours_delay_ratio: float | None = Field(default=None, ge=0)
    after_hours_response_rate: float | None = Field(default=None, ge=0, le=1)
    working_hours_slow_response_rate: float | None = Field(default=None, ge=0, le=1)
    quote_completeness_score: float | None = Field(default=None, ge=0, le=1)
    missing_quote_fields: list[str] = Field(default_factory=list)
    quote_revision_count: int | None = Field(default=None, ge=0)
    price_revision_count: int | None = Field(default=None, ge=0)
    lead_time_revision_count: int | None = Field(default=None, ge=0)
    upstream_confirmation_signal: float | None = Field(default=None, ge=0, le=1)
    supplier_current_load_signal: float | None = Field(default=None, ge=0, le=1)
    engagement_score: float | None = Field(default=None, ge=0, le=1)
    quote_response_rate: float | None = Field(default=None, ge=0, le=1)
    historical_on_time_delivery_rate: float | None = Field(default=None, ge=0, le=1)
    historical_quoted_vs_actual_error_days: float | None = None
    lead_time_confidence_score: float | None = Field(default=None, ge=0, le=1)
    price_stability_score: float | None = Field(default=None, ge=0, le=1)


class GLTGBuyerBehaviorFeatures(BaseModel):
    buyer_id: str | None = None
    buyer_response_delay_ratio: float | None = Field(default=None, ge=0)
    buyer_decision_delay_score: float | None = Field(default=None, ge=0, le=1)
    requirement_change_count: int | None = Field(default=None, ge=0)
    requirement_volatility_score: float | None = Field(default=None, ge=0, le=1)
    price_negotiation_intensity: float | None = Field(default=None, ge=0, le=1)
    lead_time_sensitivity_score: float | None = Field(default=None, ge=0, le=1)
    quality_sensitivity_score: float | None = Field(default=None, ge=0, le=1)
    sample_confirmation_delay_score: float | None = Field(default=None, ge=0, le=1)
    payment_delay_risk: float | None = Field(default=None, ge=0, le=1)
    historical_rounds_to_po: float | None = Field(default=None, ge=0)
    current_case_round_count: int | None = Field(default=None, ge=0)
    conversion_probability: float | None = Field(default=None, ge=0, le=1)
    no_response_after_quote_rate: float | None = Field(default=None, ge=0, le=1)


class GLTGPairBehaviorFeatures(BaseModel):
    buyer_id: str | None = None
    supplier_id: str | None = None
    window_type: str | None = None
    pair_rfq_count: int | None = Field(default=None, ge=0)
    pair_quote_count: int | None = Field(default=None, ge=0)
    pair_po_count: int | None = Field(default=None, ge=0)
    pair_conversion_rate: float | None = Field(default=None, ge=0, le=1)
    avg_rounds_to_po: float | None = Field(default=None, ge=0)
    avg_supplier_response_seconds: float | None = Field(default=None, ge=0)
    avg_buyer_response_seconds: float | None = Field(default=None, ge=0)
    avg_price_gap_vs_buyer_target: float | None = None
    avg_leadtime_gap_vs_buyer_target: float | None = None
    relationship_strength_score: float | None = Field(default=None, ge=0, le=1)
    recommended_pairing_score: float | None = Field(default=None, ge=0, le=1)
    dispute_count: int | None = Field(default=None, ge=0)
    quality_issue_count: int | None = Field(default=None, ge=0)
    on_time_delivery_rate: float | None = Field(default=None, ge=0, le=1)


class GLTGBehaviorFeatures(BaseModel):
    buyer_snapshot_id: str | None = None
    supplier_snapshot_id: str | None = None
    pair_metric_id: str | None = None
    supplier: GLTGSupplierBehaviorFeatures = Field(default_factory=GLTGSupplierBehaviorFeatures)
    buyer: GLTGBuyerBehaviorFeatures = Field(default_factory=GLTGBuyerBehaviorFeatures)
    pair: GLTGPairBehaviorFeatures = Field(default_factory=GLTGPairBehaviorFeatures)


class GLTGSimulationConstraintsV2(BaseModel):
    lead_time_confidence: LeadTimeConfidence = "P80"
    fallback_supplier_policy: str = "recommend_if_risk_high"
    manual_review_policy: str = "required_if_deadline_tight"
    max_acceptable_risk_level: str = "medium"


class GLTGSimulationRequestV2(BaseModel):
    request_id: str
    tenant_id: str = "tenant_default"
    source_system: str = "unknown"
    source_trace_id: str | None = None
    case_context: GLTGCaseContext = Field(default_factory=GLTGCaseContext)
    order: GLTGOrderInputV2
    supplier: GLTGSupplierInputV2 = Field(default_factory=GLTGSupplierInputV2)
    historical_baseline: GLTGHistoricalBaseline = Field(default_factory=GLTGHistoricalBaseline)
    behavior_features: GLTGBehaviorFeatures = Field(default_factory=GLTGBehaviorFeatures)
    source_observation_ids: list[str] = Field(default_factory=list)
    constraints: GLTGSimulationConstraintsV2 = Field(default_factory=GLTGSimulationConstraintsV2)


class GLTGQuantiles(BaseModel):
    p50_days: float
    p80_days: float
    p90_days: float


class GLTGComponentBreakdown(BaseModel):
    base_production_days: float = 0.0
    base_procurement_days: float = 0.0
    supplier_response_buffer_days: float = 0.0
    supplier_uncertainty_buffer_days: float = 0.0
    buyer_decision_buffer_days: float = 0.0
    logistics_buffer_days: float = 0.0
    risk_buffer_days: float = 0.0


class GLTGRiskOutput(BaseModel):
    deadline_risk_level: str = "unknown"
    confidence_score: float | None = None
    fallback_supplier_required: bool = False
    manual_review_required: bool = False
    deadline_feasible: bool | None = None
    selected_confidence_days: float | None = None


class GLTGWarningV2(BaseModel):
    code: str
    severity: str = "medium"
    message: str


class GLTGPersistenceRef(BaseModel):
    persisted_to_giraffe_db: bool = False
    gltg_behavior_input_id: str | None = None


class GLTGSimulationResponseV2(BaseModel):
    ok: bool = True
    gltg_run_id: str
    model_version: str = "gltg-hybrid-v0.1.0"
    rule_version: str = "behavior-rules-v0.1.0"
    calibration_version: str = "none"
    quantiles: GLTGQuantiles
    components: GLTGComponentBreakdown
    risk: GLTGRiskOutput
    explanation_json: dict[str, Any] = Field(default_factory=dict)
    warnings: list[GLTGWarningV2] = Field(default_factory=list)
    persistence: GLTGPersistenceRef = Field(default_factory=GLTGPersistenceRef)


class GLTGPathV2(BaseModel):
    path_id: str
    rank: int
    supplier_id: str | None = None
    quantiles: GLTGQuantiles
    risk: GLTGRiskOutput
    explanation_json: dict[str, Any] = Field(default_factory=dict)


class GLTGPathsEnumerateRequestV2(BaseModel):
    simulations: list[GLTGSimulationRequestV2] = Field(default_factory=list)


class GLTGPathsEnumerateResponseV2(BaseModel):
    ok: bool = True
    paths: list[GLTGPathV2] = Field(default_factory=list)
    warnings: list[GLTGWarningV2] = Field(default_factory=list)


class GLTGReforecastRequestV2(GLTGSimulationRequestV2):
    events: list[dict[str, Any]] = Field(default_factory=list)


class GLTGReforecastResponseV2(GLTGSimulationResponseV2):
    applied_events: list[dict[str, Any]] = Field(default_factory=list)
