"""Prompt protocol for the GLTG LLM-assisted trade lead-time risk evaluator.

The system prompt is provider-neutral: it is handed unchanged to every adapter.
It encodes the non-negotiable rules (no fact invention, status classification,
JSON-only output) so that any mainstream LLM produces a GLTG-shaped assessment.
"""

from __future__ import annotations

from typing import Any

from .schemas import ASSESSMENT_SCHEMA_VERSION, GLTGAssessmentInput, GLTGAssessmentPacket

SYSTEM_PROMPT = """\
You are a trade lead-time risk evaluator.

You must not invent facts.

Use only the provided messages, quote fields, supplier profile, buyer/supplier \
behavior features, historical observations, and operator-confirmed records.

Every conclusion must be classified as:
- confirmed
- inferred
- unknown
- needs_confirmation

If material inventory is not explicitly provided, do not mark material as confirmed.

If the supplier replies slowly, do not automatically classify it as low engagement.

If the supplier replies quickly but gives a precise lead time without material \
evidence, reduce quote confidence or require manual review.

Distinguish:
- low engagement
- material inventory check
- raw material supplier confirmation
- capacity check
- subsupplier process confirmation
- careful quotation
- timezone or holiday
- unknown

Every material conclusion must cite evidence_refs that point to provided input \
records (communication events, quotes, behavior snapshots, observations, \
operator-confirmed records). Do not cite evidence that was not provided.

Return JSON only.
The JSON must conform exactly to the provided schema.
"""


def build_user_payload(req: GLTGAssessmentInput) -> dict[str, Any]:
    """Build the structured user payload (never an unbounded NL dump)."""

    tpf = req.trade_processing_factors
    return {
        "assessment_schema_version": ASSESSMENT_SCHEMA_VERSION,
        "case_context": req.case_context.model_dump(),
        "order": req.order.model_dump(),
        "rfq_line_items": [],
        "supplier_profile": req.supplier.model_dump(),
        "supplier_quote": {
            "supplier_stated_lead_time_days": req.supplier.supplier_stated_lead_time_days,
            "confidence": req.supplier.confidence,
        },
        "supplier_messages": [],
        "buyer_messages": [],
        "behavior_features": req.behavior_features.model_dump(),
        "historical_baseline": req.historical_baseline.model_dump(),
        "trade_processing_factors": tpf.model_dump(),
        "constraints": req.constraints.model_dump(),
        "source_observation_ids": list(req.source_observation_ids),
        "operator_confirmed_facts": [],
        "unknown_fields": _unknown_fields(req),
    }


def _unknown_fields(req: GLTGAssessmentInput) -> list[str]:
    unknown: list[str] = []
    material = req.trade_processing_factors.material
    if material.material_availability_status == "unknown":
        unknown.append("material_availability_status")
    if req.supplier.supplier_stated_lead_time_days is None:
        unknown.append("supplier_stated_lead_time_days")
    if req.trade_processing_factors.supplier_execution.supplier_execution_mode == "unknown":
        unknown.append("supplier_execution_mode")
    return unknown


def assessment_schema_dict() -> dict[str, Any]:
    """JSON schema the provider must conform to (pydantic-generated)."""

    return GLTGAssessmentPacket.model_json_schema()


__all__ = ["SYSTEM_PROMPT", "build_user_payload", "assessment_schema_dict"]
