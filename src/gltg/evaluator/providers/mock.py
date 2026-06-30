"""Deterministic mock provider for CI and local development.

The mock never calls an external API. It builds a schema-valid, evidence-linked
assessment packet directly from the structured input, and supports scenario
selection (via ``GLTG_MOCK_SCENARIO`` / the ``scenario`` argument) so that the
test-suite can exercise invalid output, timeouts, and guardrail paths without
network access.
"""

from __future__ import annotations

from typing import Any

from .base import ProviderInvalidOutput, ProviderTimeout, ProviderUnavailable

SCENARIOS = {
    "valid",
    "invalid_json",
    "schema_invalid",
    "timeout",
    "error",
    "confirmed_without_evidence",
    "p90_lt_p80",
    "high_confidence_unknown_material",
}


class MockGLTGProvider:
    """Returns assessment packets from fixtures derived from the request."""

    provider_name = "mock"

    def __init__(self, *, scenario: str = "valid", model: str = "mock-gltg-1") -> None:
        self.scenario = scenario if scenario in SCENARIOS else "valid"
        self.model = model

    def evaluate_gltg_assessment(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        schema: dict[str, Any],
        model: str,
        timeout_seconds: int,
        temperature: float = 0.0,
        json_mode: bool = True,
        repair: bool = False,
        previous_error: str | None = None,
    ) -> dict[str, Any]:
        scenario = self.scenario

        if scenario == "timeout":
            raise ProviderTimeout("mock provider simulated timeout")
        if scenario == "error":
            raise ProviderUnavailable("mock provider simulated unavailability")
        if scenario == "invalid_json":
            # The adapter could not parse model output as JSON. This stays
            # invalid even on a repair pass so the outcome is deterministic.
            raise ProviderInvalidOutput("mock provider returned non-JSON content")

        packet = _base_packet(user_payload, model or self.model)

        if scenario == "schema_invalid":
            # Violates the enum contract -> pydantic validation fails downstream.
            packet["supplier_execution_assessment"]["status"] = "definitely_true"
            packet["lead_time_risk_assessment"]["deadline_risk_level"] = "catastrophic"
            return packet
        if scenario == "confirmed_without_evidence":
            packet["supplier_execution_assessment"]["status"] = "confirmed"
            packet["supplier_execution_assessment"]["confidence"] = 0.95
            packet["supplier_execution_assessment"]["evidence_refs"] = []
            return packet
        if scenario == "p90_lt_p80":
            lt = packet["lead_time_risk_assessment"]
            lt["p50_days"] = 30.0
            lt["p80_days"] = 40.0
            lt["p90_days"] = 25.0  # invalid ordering -> validator must repair
            return packet
        if scenario == "high_confidence_unknown_material":
            packet["material_availability_assessment"]["material_availability_status"] = "unknown"
            packet["material_availability_assessment"]["status"] = "unknown"
            packet["material_availability_assessment"]["evidence_refs"] = []
            packet["quote_confidence_assessment"]["quote_confidence_level"] = "high"
            packet["quote_confidence_assessment"]["confidence_score"] = 0.95
            packet["quote_confidence_assessment"]["status"] = "confirmed"
            packet["quote_confidence_assessment"]["evidence_refs"] = []
            return packet

        return packet


def _evidence_from_payload(user_payload: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    case = user_payload.get("case_context", {}) or {}
    for key in ("procurement_case_id", "rfq_id", "quote_id"):
        value = case.get(key)
        if value:
            refs.append(value)
    refs.extend([oid for oid in user_payload.get("source_observation_ids", []) if oid])
    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            ordered.append(ref)
    return ordered


def _base_packet(user_payload: dict[str, Any], model: str) -> dict[str, Any]:
    tpf = user_payload.get("trade_processing_factors", {}) or {}
    material = tpf.get("material", {}) or {}
    supplier_exec = tpf.get("supplier_execution", {}) or {}
    order = user_payload.get("order", {}) or {}
    baseline = user_payload.get("historical_baseline", {}) or {}
    evidence = _evidence_from_payload(user_payload)
    has_evidence = bool(evidence)

    material_status = material.get("material_availability_status") or "unknown"
    material_assessment_status = "inferred" if material_status != "unknown" else "needs_confirmation"
    # Material evidence only exists when the material status itself is supported.
    material_evidence = evidence if material_status not in {"unknown"} else []

    # Conservative quantiles anchored on whatever baseline/quote data exists.
    p50 = float(baseline.get("baseline_p50_days") or 0) or _stated_lead_time(user_payload) or 30.0
    p80 = float(baseline.get("baseline_p80_days") or 0) or p50 * 1.2
    p90 = float(baseline.get("baseline_p90_days") or 0) or p50 * 1.4
    if material_status in {"unknown", "supplier_confirmation_required", "not_available"}:
        p80 += 4.0
        p90 += 8.0

    deadline = order.get("deadline_days")
    deadline_risk = "unknown"
    if deadline is not None:
        if p80 <= deadline:
            deadline_risk = "low"
        elif p50 <= deadline:
            deadline_risk = "medium_high"
        else:
            deadline_risk = "high"

    exec_mode = supplier_exec.get("supplier_execution_mode") or "unknown"
    exec_mode = _map_execution_mode(exec_mode)

    return {
        "assessment_schema_version": user_payload.get(
            "assessment_schema_version", "gltg-assessment-v1"
        ),
        "model_provider": "mock",
        "model_name": model,
        "model_version": None,
        "evaluation_mode": "llm",
        "case_context": user_payload.get("case_context", {}),
        "supplier_execution_assessment": {
            "execution_mode": exec_mode,
            "status": "inferred" if exec_mode != "unknown" else "unknown",
            "confidence": 0.55 if has_evidence else 0.3,
            "evidence_refs": evidence,
            "reasoning_summary": "Execution mode inferred from supplier profile and behavior features.",
            "alternative_modes": [],
        },
        "material_availability_assessment": {
            "material_availability_status": material_status,
            "status": material_assessment_status,
            "confidence": 0.5 if has_evidence else 0.25,
            "stock_coverage_ratio": material.get("stock_coverage_ratio"),
            "raw_material_supplier_confirmation_required": material_status
            in {"supplier_confirmation_required", "not_available", "unknown"},
            "raw_material_lead_time_estimate_days": material.get(
                "raw_material_lead_time_estimate_days"
            ),
            "material_lock_required": None,
            "material_lock_validity_days": None,
            "substitute_material_required": material_status == "substitute_material_required",
            "evidence_refs": material_evidence,
            "reasoning_summary": "Material availability inferred from provided trade factors.",
        },
        "response_delay_reason_assessment": _delay_reason(material_status, evidence),
        "quote_confidence_assessment": {
            "quote_confidence_level": "medium" if has_evidence else "low",
            "confidence_score": 0.6 if has_evidence else 0.35,
            "status": "inferred",
            "complete_fields": ["supplier_stated_lead_time_days"]
            if _stated_lead_time(user_payload)
            else [],
            "missing_fields": [] if material_status != "unknown" else ["material_availability_status"],
            "unsupported_claims": [],
            "evidence_refs": evidence,
            "reasoning_summary": "Quote confidence derived from completeness and evidence.",
        },
        "lead_time_risk_assessment": {
            "p50_days": round(p50, 2),
            "p80_days": round(p80, 2),
            "p90_days": round(p90, 2),
            "deadline_risk_level": deadline_risk,
            "main_risk_drivers": _risk_drivers(material_status),
            "p50_drivers": ["base_production", "base_procurement"],
            "p80_p90_tail_drivers": _risk_drivers(material_status),
            "risk_decomposition": {
                "material_availability_risk": 0.6
                if material_status in {"unknown", "supplier_confirmation_required", "not_available"}
                else 0.1,
                "upstream_dependency_risk": float(
                    supplier_exec.get("upstream_dependency_probability") or 0.0
                ),
            },
            "evidence_refs": evidence,
            "reasoning_summary": "Quantiles anchored on baseline and widened for material uncertainty.",
        },
        "trade_processing_factor_assessments": {},
        "evidence_refs": evidence,
        "missing_information": [] if material_status != "unknown" else ["material_availability_status"],
        "follow_up_questions": _follow_ups(material_status),
        "manual_review": {"required": False, "reasons": []},
        "fallback_supplier": {"required": False, "reasons": []},
        "pricing_implications": {},
        "audit": {
            "model_provider": "mock",
            "model_name": model,
            "evaluation_mode": "llm",
        },
    }


def _delay_reason(material_status: str, evidence: list[str]) -> dict[str, Any]:
    if material_status == "supplier_confirmation_required":
        probabilities = {
            "material_inventory_check": 0.1,
            "raw_material_supplier_confirmation": 0.4,
            "capacity_check": 0.1,
            "subsupplier_process_confirmation": 0.1,
            "low_engagement": 0.1,
            "careful_quotation": 0.1,
            "timezone_or_holiday": 0.05,
            "unknown": 0.05,
        }
        reason = "raw_material_supplier_confirmation"
    else:
        probabilities = {
            "material_inventory_check": 0.1,
            "raw_material_supplier_confirmation": 0.1,
            "capacity_check": 0.1,
            "subsupplier_process_confirmation": 0.1,
            "low_engagement": 0.1,
            "careful_quotation": 0.1,
            "timezone_or_holiday": 0.05,
            "unknown": 0.35,
        }
        reason = "unknown"
    return {
        "most_likely_reason": reason,
        "status": "inferred",
        "confidence": probabilities[reason],
        "probabilities": probabilities,
        "evidence_refs": evidence,
        "reasoning_summary": "Delay reason inferred without assuming low engagement.",
    }


def _stated_lead_time(user_payload: dict[str, Any]) -> float:
    quote = user_payload.get("supplier_quote", {}) or {}
    value = quote.get("supplier_stated_lead_time_days")
    return float(value) if value else 0.0


def _map_execution_mode(mode: str) -> str:
    # The input vocabulary (behavioral schema) differs from the assessment
    # vocabulary; map without leaking provider/input-specific naming.
    mapping = {
        "in_house_manufacturer": "in_house_manufacturer",
        "factory_without_stock": "material_dependent_manufacturer",
        "trader": "trader_or_broker",
        "broker": "trader_or_broker",
        "hybrid": "partial_outsource",
        "unknown": "unknown",
    }
    return mapping.get(mode, "unknown")


def _risk_drivers(material_status: str) -> list[str]:
    if material_status in {"unknown", "supplier_confirmation_required", "not_available"}:
        return ["material_availability", "upstream_dependency"]
    return ["execution_control"]


def _follow_ups(material_status: str) -> list[str]:
    questions = [
        "Do you manufacture this item in-house or through an upstream factory?",
    ]
    if material_status in {"unknown", "supplier_confirmation_required", "not_available"}:
        questions.extend(
            [
                "Do you have the required raw material in stock?",
                "If material is not in stock, how long does your material supplier need to confirm availability?",
                "What is the raw material lead time to your factory?",
            ]
        )
    return questions


__all__ = ["MockGLTGProvider", "SCENARIOS"]
