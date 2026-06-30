"""Prompt contract tests (§18.3)."""

from __future__ import annotations

from gltg.evaluator.prompts import (
    SYSTEM_PROMPT,
    assessment_schema_dict,
    build_user_payload,
)


def test_system_prompt_forbids_fact_invention():
    assert "must not invent facts" in SYSTEM_PROMPT


def test_system_prompt_requires_status_classification():
    for status in ("confirmed", "inferred", "unknown", "needs_confirmation"):
        assert status in SYSTEM_PROMPT


def test_system_prompt_slow_response_not_low_engagement():
    assert "do not automatically classify it as low engagement" in SYSTEM_PROMPT


def test_system_prompt_fast_response_without_material_evidence():
    assert "without material" in SYSTEM_PROMPT
    assert "reduce quote confidence or require manual review" in SYSTEM_PROMPT


def test_system_prompt_requires_json_only():
    assert "Return JSON only." in SYSTEM_PROMPT


def test_user_payload_is_structured_not_freeform(make_request):
    payload = build_user_payload(make_request())
    for section in (
        "case_context",
        "order",
        "supplier_profile",
        "supplier_quote",
        "behavior_features",
        "historical_baseline",
        "trade_processing_factors",
        "constraints",
        "source_observation_ids",
        "operator_confirmed_facts",
        "unknown_fields",
    ):
        assert section in payload


def test_assessment_schema_is_emitted():
    schema = assessment_schema_dict()
    assert schema["title"] == "GLTGAssessmentPacket"
    assert "lead_time_risk_assessment" in schema["properties"]
