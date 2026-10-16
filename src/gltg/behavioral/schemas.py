"""GLTG v2 behavior-aware lead-time API schemas.

This contract is the standalone service boundary for product repositories.
Products send observed facts and feature snapshots; GLTG owns simulation,
composition, risk flags, and explanations.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class FiniteContractModel(BaseModel):
    """API model values must have finite numerical representations."""

    model_config = ConfigDict(allow_inf_nan=False)

LeadTimeConfidence = Literal["P50", "P80", "P90"]
TenantId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
MaterialAvailabilityStatus = Literal[
    "in_stock",
    "reserved_stock",
    "partial_stock",
    "supplier_confirmation_required",
    "not_available",
    "substitute_material_required",
    "unknown",
]
SupplierExecutionMode = Literal[
    "in_house_manufacturer",
    "factory_without_stock",
    "trader",
    "broker",
    "hybrid",
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


class GLTGCaseContext(FiniteContractModel):
    procurement_case_id: str | None = None
    rfq_id: str | None = None
    quote_id: str | None = None
    po_id: str | None = None
    buyer_id: str | None = None
    supplier_id: str | None = None
    assessment_scope: Literal["requirement_baseline", "supplier_candidate"] | None = None


class GLTGOrderInputV2(FiniteContractModel):
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
    target_delivery_date: date | None = None
    evaluation_date: date | None = None
    quality_requirement_level: str | None = None
    packaging_requirement_level: str | None = None

    @model_validator(mode="after")
    def bind_absolute_target(self):
        if self.target_delivery_date is not None:
            if self.evaluation_date is not None:
                days = (self.target_delivery_date - self.evaluation_date).days
                if days < 0:
                    raise ValueError("target_delivery_date precedes evaluation_date")
                self.deadline_days = days
            elif self.deadline_days is None:
                raise ValueError("evaluation_date is required for a date-only delivery target")
        return self


class GLTGSupplierInputV2(FiniteContractModel):
    supplier_id: str | None = None
    name: str | None = None
    capacity_per_day: int | None = Field(default=None, ge=0)
    material_ready_days: float | None = Field(default=None, ge=0)
    production_days: float | None = Field(default=None, ge=0)
    qc_days: float | None = Field(default=None, ge=0)
    logistics_days: float | None = Field(default=None, ge=0)
    supplier_stated_lead_time_days: float | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class GLTGHistoricalBaseline(FiniteContractModel):
    baseline_source: str | None = None
    sample_size: int | None = Field(default=None, ge=0)
    baseline_p50_days: float | None = Field(default=None, ge=0)
    baseline_p80_days: float | None = Field(default=None, ge=0)
    baseline_p90_days: float | None = Field(default=None, ge=0)
    historical_quoted_vs_actual_error_days: float | None = None
    on_time_delivery_rate: float | None = Field(default=None, ge=0.0, le=1.0)


class GLTGSupplierBehaviorFeatures(FiniteContractModel):
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


class GLTGBuyerBehaviorFeatures(FiniteContractModel):
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


class GLTGPairBehaviorFeatures(FiniteContractModel):
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


class GLTGBehaviorFeatures(FiniteContractModel):
    buyer_snapshot_id: str | None = None
    supplier_snapshot_id: str | None = None
    pair_metric_id: str | None = None
    supplier: GLTGSupplierBehaviorFeatures = Field(default_factory=GLTGSupplierBehaviorFeatures)
    buyer: GLTGBuyerBehaviorFeatures = Field(default_factory=GLTGBuyerBehaviorFeatures)
    pair: GLTGPairBehaviorFeatures = Field(default_factory=GLTGPairBehaviorFeatures)


class GLTGRequirementFactors(FiniteContractModel):
    completed_required_fields: int | None = Field(default=None, ge=0)
    total_required_fields: int | None = Field(default=None, gt=0)
    requirement_completeness_score: float | None = Field(default=None, ge=0, le=1)
    requirement_volatility_score: float | None = Field(default=None, ge=0, le=1)
    deadline_strictness_score: float | None = Field(default=None, ge=0, le=1)
    quality_requirement_level_score: float | None = Field(default=None, ge=0, le=1)
    packaging_complexity_score: float | None = Field(default=None, ge=0, le=1)
    sample_approval_delay_score: float | None = Field(default=None, ge=0, le=1)
    payment_delay_risk: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def derive_completeness(self):
        if self.completed_required_fields is not None and self.total_required_fields is not None:
            if self.completed_required_fields > self.total_required_fields:
                raise ValueError("completed required fields cannot exceed total required fields")
            score = self.completed_required_fields / self.total_required_fields
            if self.requirement_completeness_score is not None and abs(self.requirement_completeness_score - score) > 1e-9:
                raise ValueError("requirement completeness conflicts with category-defined counts")
            self.requirement_completeness_score = score
        return self


class GLTGSupplierExecutionFactors(FiniteContractModel):
    supplier_execution_mode: SupplierExecutionMode = "unknown"
    in_house_capability_confidence: float | None = Field(default=None, ge=0, le=1)
    upstream_dependency_probability: float | None = Field(default=None, ge=0, le=1)
    execution_control_score: float | None = Field(default=None, ge=0, le=1)
    capacity_utilization_ratio: float | None = Field(default=None, ge=0)
    nominal_daily_capacity: float | None = Field(default=None, ge=0)
    effective_daily_capacity: float | None = Field(default=None, ge=0)
    priority_factor: float | None = Field(default=None, ge=0)


class GLTGMaterialFactors(FiniteContractModel):
    required_material_qty: float | None = Field(default=None, gt=0)
    available_material_qty: float | None = Field(default=None, ge=0)
    material_availability_status: MaterialAvailabilityStatus = "unknown"
    stock_coverage_ratio: float | None = Field(default=None, ge=0)
    material_availability_confidence: float | None = Field(default=None, ge=0, le=1)
    raw_material_supplier_confirmation_probability: float | None = Field(default=None, ge=0, le=1)
    raw_material_lead_time_estimate_days: float | None = Field(default=None, ge=0)
    raw_material_lead_time_uncertainty_score: float | None = Field(default=None, ge=0, le=1)
    substitute_material_probability: float | None = Field(default=None, ge=0, le=1)
    material_lock_required: bool = False
    material_lock_validity_days: float | None = Field(default=None, ge=0)
    historical_material_delay_rate: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def derive_stock_coverage(self):
        if self.required_material_qty is not None and self.available_material_qty is not None:
            ratio = self.available_material_qty / self.required_material_qty
            if self.stock_coverage_ratio is not None and abs(self.stock_coverage_ratio - ratio) > 1e-9:
                raise ValueError("stock_coverage_ratio conflicts with material quantities")
            self.stock_coverage_ratio = ratio
        ratio = self.stock_coverage_ratio
        if self.material_availability_status == "unknown" and ratio is not None:
            if ratio >= 1:
                self.material_availability_status = "in_stock"
            elif ratio > 0:
                self.material_availability_status = "partial_stock"
        return self


class GLTGProcessingFactors(FiniteContractModel):
    category_default_production_days: float | None = Field(default=None, ge=0)
    quantity_band_multiplier: float | None = Field(default=None, ge=0)
    base_category_defect_rate: float | None = Field(default=None, ge=0, le=1)
    new_supplier_flag: bool = False
    material_substitution_flag: bool = False
    rushed_order_flag: bool = False
    historical_quality_score: float | None = Field(default=None, ge=0, le=1)
    process_complexity_score: float | None = Field(default=None, ge=0, le=1)
    customization_level_score: float | None = Field(default=None, ge=0, le=1)
    tooling_required: bool = False
    tooling_days: float | None = Field(default=None, ge=0)
    sample_required: bool = False
    sample_days: float | None = Field(default=None, ge=0)
    color_approval_required: bool = False
    color_approval_days: float | None = Field(default=None, ge=0)
    external_subprocess_dependency_score: float | None = Field(default=None, ge=0, le=1)
    setup_days: float | None = Field(default=None, ge=0)
    subprocess_days: float | None = Field(default=None, ge=0)
    expected_yield_rate: float | None = Field(default=None, ge=0, le=1)
    qc_intensity_score: float | None = Field(default=None, ge=0, le=1)
    rework_probability: float | None = Field(default=None, ge=0, le=1)
    rework_days_if_triggered: float | None = Field(default=None, ge=0)


class GLTGLogisticsTradeFactors(FiniteContractModel):
    logistics_disruption_buffer_days: float | None = Field(default=None, ge=0)
    booking_confirmed: bool = False
    expected_customs_delay_days: float | None = Field(default=None, ge=0)
    manual_review_delay_days: float | None = Field(default=None, ge=0)
    incoterms: str | None = None
    logistics_mode: str | None = None
    route_baseline_days: float | None = Field(default=None, ge=0)
    departure_frequency_days: float | None = Field(default=None, ge=0)
    freight_space_risk: float | None = Field(default=None, ge=0, le=1)
    export_doc_readiness_score: float | None = Field(default=None, ge=0, le=1)
    customs_inspection_probability: float | None = Field(default=None, ge=0, le=1)
    trade_compliance_risk: float | None = Field(default=None, ge=0, le=1)
    origin_inland_days: float | None = Field(default=None, ge=0)
    destination_inland_days: float | None = Field(default=None, ge=0)
    import_clearance_days: float | None = Field(default=None, ge=0)
    calendar_disruption_score: float | None = Field(default=None, ge=0, le=1)
    logistics_disruption_score: float | None = Field(default=None, ge=0, le=1)


class GLTGCommunicationBehaviorFactors(FiniteContractModel):
    current_case_supplier_response_seconds: float | None = Field(default=None, ge=0)
    supplier_historical_response_seconds: float | None = Field(default=None, ge=0)
    pair_historical_response_seconds: float | None = Field(default=None, ge=0)
    category_baseline_response_seconds: float | None = Field(default=None, ge=0)
    tenant_baseline_response_seconds: float | None = Field(default=None, ge=0)
    global_default_response_seconds: float | None = Field(default=None, gt=0)
    current_case_business_hours_response_seconds: float | None = Field(default=None, ge=0)
    historical_business_hours_response_seconds: float | None = Field(default=None, gt=0)
    supplier_response_delay_ratio: float | None = Field(default=None, ge=0)
    business_hours_delay_ratio: float | None = Field(default=None, ge=0)
    quote_completeness_score: float | None = Field(default=None, ge=0, le=1)
    quote_confidence_score: float | None = Field(default=None, ge=0, le=1)
    most_likely_response_delay_reason: ResponseDelayReason | None = None
    low_engagement_probability: float | None = Field(default=None, ge=0, le=1)
    careful_quotation_probability: float | None = Field(default=None, ge=0, le=1)
    missing_lead_time: bool = False
    missing_material_status: bool = False
    supplier_response_fast: bool = False
    unsupported_precise_leadtime_signal: bool = False
    material_keywords: float | None = Field(default=None, ge=0, le=1)
    explicit_material_supplier_signal: float | None = Field(default=None, ge=0, le=1)
    capacity_keywords: float | None = Field(default=None, ge=0, le=1)
    production_schedule_keywords: float | None = Field(default=None, ge=0, le=1)
    detailed_breakdown_signal: float | None = Field(default=None, ge=0, le=1)
    explicit_checking_signal: float | None = Field(default=None, ge=0, le=1)
    non_working_time_overlap: float | None = Field(default=None, ge=0, le=1)
    holiday_calendar_match: float | None = Field(default=None, ge=0, le=1)
    no_clear_reason_signal: float | None = Field(default=None, ge=0, le=1)

    def response_baseline(self):
        for field_name in (
            "supplier_historical_response_seconds", "pair_historical_response_seconds",
            "category_baseline_response_seconds", "tenant_baseline_response_seconds", "global_default_response_seconds",
        ):
            seconds = getattr(self, field_name)
            if seconds is not None and seconds > 0:
                return field_name, seconds
        return None, None

    @model_validator(mode="after")
    def derive_response_ratios(self):
        _, baseline = self.response_baseline()
        current = self.current_case_supplier_response_seconds
        if current is not None and baseline is not None:
            ratio = current / baseline
            if self.supplier_response_delay_ratio is not None and abs(self.supplier_response_delay_ratio - ratio) > 1e-9:
                raise ValueError("supplier response ratio conflicts with timing evidence")
            self.supplier_response_delay_ratio = ratio
        if self.current_case_business_hours_response_seconds is not None and self.historical_business_hours_response_seconds is not None:
            ratio = self.current_case_business_hours_response_seconds / self.historical_business_hours_response_seconds
            if self.business_hours_delay_ratio is not None and abs(self.business_hours_delay_ratio - ratio) > 1e-9:
                raise ValueError("business hours response ratio conflicts with timing evidence")
            self.business_hours_delay_ratio = ratio
        return self


class GLTGTradeProcessingFactors(FiniteContractModel):
    requirement: GLTGRequirementFactors = Field(default_factory=GLTGRequirementFactors)
    supplier_execution: GLTGSupplierExecutionFactors = Field(default_factory=GLTGSupplierExecutionFactors)
    material: GLTGMaterialFactors = Field(default_factory=GLTGMaterialFactors)
    processing: GLTGProcessingFactors = Field(default_factory=GLTGProcessingFactors)
    logistics_trade: GLTGLogisticsTradeFactors = Field(default_factory=GLTGLogisticsTradeFactors)
    behavior: GLTGCommunicationBehaviorFactors = Field(default_factory=GLTGCommunicationBehaviorFactors)


class GLTGSimulationConstraintsV2(FiniteContractModel):
    lead_time_confidence: LeadTimeConfidence = "P80"
    fallback_supplier_policy: str = "recommend_if_risk_high"
    manual_review_policy: str = "required_if_deadline_tight"
    max_acceptable_risk_level: str = "medium"


class GLTGEvidenceRequestV2(FiniteContractModel):
    """Explicit opt-in for GLTG to retrieve evidence from giraffe-db.

    When ``use_giraffe_db`` is true, GLTG fetches the supplier record and
    behavior summary for ``supplier.supplier_id`` under the request's
    ``tenant_id``. GLTG never fabricates evidence: retrieval failures surface
    as explicit warnings/errors, never as guessed local values.
    """

    use_giraffe_db: bool = False


class GLTGSimulationRequestV2(FiniteContractModel):
    request_id: str
    tenant_id: TenantId
    source_system: str = "unknown"
    source_trace_id: str | None = None
    case_context: GLTGCaseContext = Field(default_factory=GLTGCaseContext)
    order: GLTGOrderInputV2
    supplier: GLTGSupplierInputV2 = Field(default_factory=GLTGSupplierInputV2)
    historical_baseline: GLTGHistoricalBaseline = Field(default_factory=GLTGHistoricalBaseline)
    behavior_features: GLTGBehaviorFeatures = Field(default_factory=GLTGBehaviorFeatures)
    trade_processing_factors: GLTGTradeProcessingFactors = Field(default_factory=GLTGTradeProcessingFactors)
    source_observation_ids: list[str] = Field(default_factory=list)
    evidence: GLTGEvidenceRequestV2 = Field(default_factory=GLTGEvidenceRequestV2)
    constraints: GLTGSimulationConstraintsV2 = Field(default_factory=GLTGSimulationConstraintsV2)


class GLTGQuantiles(FiniteContractModel):
    p50_days: float = Field(ge=0, allow_inf_nan=False)
    p80_days: float = Field(ge=0, allow_inf_nan=False)
    p90_days: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _ordered(self) -> GLTGQuantiles:
        if not self.p50_days <= self.p80_days <= self.p90_days:
            raise ValueError("quantiles must satisfy P50 <= P80 <= P90")
        return self


class GLTGComponentBreakdown(FiniteContractModel):
    logistics_disruption_buffer_days: float = 0.0
    customs_risk_buffer_days: float = 0.0
    base_production_days: float = 0.0
    base_procurement_days: float = 0.0
    requirement_confirmation_days: float = 0.0
    supplier_response_buffer_days: float = 0.0
    material_confirmation_days: float = 0.0
    material_procurement_days: float = 0.0
    preproduction_days: float = 0.0
    capacity_queue_days: float = 0.0
    production_days: float = 0.0
    subprocess_days: float = 0.0
    qc_days: float = 0.0
    expected_rework_days: float = 0.0
    packaging_days: float = 0.0
    export_preparation_days: float = 0.0
    origin_inland_days: float = 0.0
    departure_wait_days: float = 0.0
    main_freight_days: float = 0.0
    import_clearance_days: float = 0.0
    destination_inland_days: float = 0.0
    supplier_uncertainty_buffer_days: float = 0.0
    buyer_decision_buffer_days: float = 0.0
    logistics_buffer_days: float = 0.0
    risk_buffer_days: float = 0.0


class GLTGRiskDecomposition(FiniteContractModel):
    engagement_risk: float = 0.0
    execution_control_risk: float = 0.0
    upstream_dependency_risk: float = 0.0
    material_availability_risk: float = 0.0
    capacity_risk: float = 0.0
    process_complexity_risk: float = 0.0
    quality_rework_risk: float = 0.0
    logistics_risk: float = 0.0
    customs_compliance_risk: float = 0.0
    buyer_delay_risk: float = 0.0
    quote_confidence_penalty: float = 0.0
    lead_time_uncertainty_risk: float = 0.0


class GLTGResponseDelayReasonInference(FiniteContractModel):
    most_likely_reason: ResponseDelayReason = "unknown"
    confidence: float = 0.0
    probabilities: dict[str, float] = Field(default_factory=dict)


class GLTGRiskOutput(FiniteContractModel):
    deadline_risk_level: str = "unknown"
    confidence_score: float | None = None
    fallback_supplier_required: bool = False
    manual_review_required: bool = False
    deadline_feasible: bool | None = None
    selected_confidence_days: float | None = None


class GLTGWarningV2(FiniteContractModel):
    code: str
    severity: str = "medium"
    message: str


class GLTGPersistenceRef(FiniteContractModel):
    """Truthful persistence outcome for a run.

    status values:
      * ``unavailable`` — giraffe-db persistence is not configured;
      * ``skipped``     — configured but explicitly disabled for this run;
      * ``persisted``   — giraffe-db accepted the run (id in giraffe_db_run_id);
      * ``failed``      — a persistence attempt was made and failed.
    """

    status: str = "unavailable"
    readback_status: str = "not_requested"
    idempotency_key: str | None = None
    persisted_to_giraffe_db: bool = False
    giraffe_db_run_id: str | None = None
    gltg_behavior_input_id: str | None = None
    detail: str | None = None


class GLTGSimulationResponseV2(FiniteContractModel):
    ok: bool = True
    gltg_run_id: str
    # Evaluator metadata. Deterministic rules are the default engine; the
    # provider fields identify the LLM only in explicit opt-in llm mode.
    assessment_schema_version: str = "gltg-assessment-v1"
    model_provider: str = "deterministic_rules"
    model_name: str = "behavior-rules-v0.1.0"
    evaluation_mode: str = "deterministic"
    model_version: str = "gltg-hybrid-v0.1.0"
    rule_version: str = "behavior-rules-v0.3.0"
    calibration_version: str = "none"
    quantiles: GLTGQuantiles
    components: GLTGComponentBreakdown = Field(default_factory=GLTGComponentBreakdown)
    risk_decomposition: GLTGRiskDecomposition = Field(default_factory=GLTGRiskDecomposition)
    response_delay_reason_inference: GLTGResponseDelayReasonInference = Field(
        default_factory=GLTGResponseDelayReasonInference
    )
    risk: GLTGRiskOutput
    # Structured GLTG Assessment Packet (or a normalized projection of it).
    assessment_packet: dict[str, Any] = Field(default_factory=dict)
    manual_review_required: bool = False
    fallback_supplier_required: bool = False
    explanation_json: dict[str, Any] = Field(default_factory=dict)
    warnings: list[GLTGWarningV2] = Field(default_factory=list)
    persistence: GLTGPersistenceRef = Field(default_factory=GLTGPersistenceRef)
    # Lineage: IDs are echoed from the request and/or returned by giraffe-db
    # evidence retrieval; GLTG never invents observation IDs.
    source_observation_ids: list[str] = Field(default_factory=list)


class GLTGPathV2(FiniteContractModel):
    path_id: str
    rank: int
    supplier_id: str | None = None
    quantiles: GLTGQuantiles
    risk: GLTGRiskOutput
    explanation_json: dict[str, Any] = Field(default_factory=dict)


class GLTGPathsEnumerateRequestV2(FiniteContractModel):
    simulations: list[GLTGSimulationRequestV2] = Field(default_factory=list)


class GLTGPathsEnumerateResponseV2(FiniteContractModel):
    ok: bool = True
    paths: list[GLTGPathV2] = Field(default_factory=list)
    warnings: list[GLTGWarningV2] = Field(default_factory=list)


class GLTGReforecastRequestV2(GLTGSimulationRequestV2):
    events: list[dict[str, Any]] = Field(default_factory=list)


class GLTGReforecastDeltaV2(FiniteContractModel):
    p50_days: float = 0.0
    p80_days: float = 0.0
    p90_days: float = 0.0


class GLTGReforecastResponseV2(GLTGSimulationResponseV2):
    applied_events: list[dict[str, Any]] = Field(default_factory=list)
    unapplied_events: list[dict[str, Any]] = Field(default_factory=list)
    previous_quantiles: GLTGQuantiles | None = None
    delta: GLTGReforecastDeltaV2 | None = None
    changed_components: dict[str, float] = Field(default_factory=dict)
    triggering_observation_ids: list[str] = Field(default_factory=list)
