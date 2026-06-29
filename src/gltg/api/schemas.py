"""HTTP API request/response schemas for the GLTG service.

These are the stable, API-first DTOs that all consumer repositories
(giraffe-agent, abcdYi, aivan) integrate against. They are intentionally
simpler than the internal engine domain models in ``gltg.models`` -- the
service layer (``gltg.services``) maps between this transport contract and
the deterministic lead-time/path/reforecast logic.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Shared building blocks
# --------------------------------------------------------------------------- #
class OrderInput(BaseModel):
    """The order being evaluated."""

    product_type: str = "apparel"
    quantity: int = Field(..., ge=0)
    target_delivery_date: date | None = None
    # Optional explicit anchor for deterministic date math; defaults to today.
    evaluation_date: date | None = None
    # Requirement-level hints used to synthesize baseline stage estimates when a
    # supplier omits explicit stage durations (keeps all baseline math in GLTG).
    destination: str | None = None
    logistics_mode: str | None = None  # "sea" | "air"
    deadline_days: int | None = None


class SupplierInput(BaseModel):
    """A single supplier's stated stage durations and capacity."""

    supplier_id: str
    name: str | None = None
    capacity_per_day: int | None = Field(default=None, ge=0)
    material_ready_days: float = Field(default=0.0, ge=0)
    production_days: float = Field(default=0.0, ge=0)
    qc_days: float = Field(default=0.0, ge=0)
    logistics_days: float = Field(default=0.0, ge=0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class Constraints(BaseModel):
    """Optional evaluation constraints."""

    allow_partial_suppliers: bool = True
    min_supplier_count: int = 0
    currency: str = "USD"


class Warning(BaseModel):
    """Structured, machine-readable warning (never free-form only)."""

    code: str
    message: str


# --------------------------------------------------------------------------- #
# /v1/lead-time/estimate
# --------------------------------------------------------------------------- #
class LeadTimeEstimateRequest(BaseModel):
    order: OrderInput
    suppliers: list[SupplierInput] = []
    constraints: Constraints = Constraints()


class SupplierTrace(BaseModel):
    """Deterministic per-supplier stage breakdown for auditability."""

    supplier_id: str
    material_ready_days: float
    production_days: float
    capacity_adjusted_production_days: float
    qc_days: float
    logistics_days: float
    total_lead_time_days: float
    confidence: float
    feasible: bool


class LeadTimeEstimateResponse(BaseModel):
    status: str = "ok"
    estimated_lead_time_days: float | None = None
    earliest_delivery_date: date | None = None
    feasible: bool = False
    supplier_count: int = 0
    selected_supplier_id: str | None = None
    # Deterministic confidence bands derived from the selected supplier's
    # confidence (GLTG owns these; consumers must not recompute them).
    p50_days: float | None = None
    p80_days: float | None = None
    p90_days: float | None = None
    minimum_feasible_days: float | None = None
    risk_level: str = "unknown"  # low | medium | high | unknown
    # Additive engine-derived fields (DEFECT-01): the graph engine is the source
    # of truth for these dates. Optional so existing consumers are unaffected.
    most_likely_date: date | None = None
    committable_date: date | None = None
    risk_adjusted_date: date | None = None
    on_time_probability: float | None = None
    feasibility: str | None = None  # engine FeasibilityStatus value
    warnings: list[Warning] = []
    calculation_trace: list[SupplierTrace] = []


# --------------------------------------------------------------------------- #
# /v1/paths/enumerate
# --------------------------------------------------------------------------- #
class PathEnumerateRequest(BaseModel):
    order: OrderInput
    suppliers: list[SupplierInput] = []
    constraints: Constraints = Constraints()


class DeliveryPath(BaseModel):
    path_id: str
    rank: int
    mode: str  # SINGLE_SOURCE | PARALLEL_SPLIT
    supplier_ids: list[str]
    estimated_lead_time_days: float
    earliest_delivery_date: date | None = None
    feasible: bool
    confidence: float
    score: float
    warnings: list[Warning] = []


class PathEnumerateResponse(BaseModel):
    status: str = "ok"
    supplier_count: int = 0
    paths: list[DeliveryPath] = []
    warnings: list[Warning] = []


# --------------------------------------------------------------------------- #
# /v1/reforecast
# --------------------------------------------------------------------------- #
class ReforecastEvent(BaseModel):
    """An updated fact applied on top of the baseline (never mutates history)."""

    supplier_id: str
    # Additive deltas in days for any stage; positive = delay, negative = pull-in.
    material_ready_days_delta: float = 0.0
    production_days_delta: float = 0.0
    qc_days_delta: float = 0.0
    logistics_days_delta: float = 0.0
    note: str | None = None


class ReforecastRequest(BaseModel):
    order: OrderInput
    suppliers: list[SupplierInput] = []
    events: list[ReforecastEvent] = []
    constraints: Constraints = Constraints()


class ReforecastResponse(BaseModel):
    status: str = "ok"
    baseline_lead_time_days: float | None = None
    updated_lead_time_days: float | None = None
    delta_days: float | None = None
    earliest_delivery_date: date | None = None
    feasible: bool = False
    supplier_count: int = 0
    selected_supplier_id: str | None = None
    applied_events: list[dict[str, Any]] = []
    warnings: list[Warning] = []
    calculation_trace: list[SupplierTrace] = []


# --------------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------------- #
class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "gltg"


class VersionResponse(BaseModel):
    service: str = "gltg"
    version: str
    api_version: str = "v1"


# --------------------------------------------------------------------------- #
# Supplier Signal / Questionnaire (next iteration)
# --------------------------------------------------------------------------- #
class QuestionnaireEnquiryContext(BaseModel):
    """Context sent to aivan when triggering a per-enquiry questionnaire."""
    enquiry_id: str
    supplier_id: str
    product_type: str
    quantity: int
    destination: str
    deadline_days: int | None = None
    lead_time_estimate_p50: int | None = None   # populated from GLTG output


class QuestionnaireResponse(BaseModel):
    """aivan's extracted questionnaire result."""
    status: str                     # "ok" | "error"
    output: str                     # human-readable LLM response
    extracted_fields: dict = {}     # structured fields extracted by LLM
