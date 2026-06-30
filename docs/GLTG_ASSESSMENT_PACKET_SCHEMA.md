# GLTG Assessment Packet Schema (`gltg-assessment-v1`)

The primary output of the evaluator is a structured, evidence-linked assessment
packet. Defined in `src/gltg/evaluator/schemas.py`.

## Top-level fields

```json
{
  "assessment_schema_version": "gltg-assessment-v1",
  "model_provider": "qwen",
  "model_name": "qwen3.5",
  "model_version": null,
  "evaluation_mode": "llm",
  "case_context": {},
  "supplier_execution_assessment": {},
  "material_availability_assessment": {},
  "response_delay_reason_assessment": {},
  "quote_confidence_assessment": {},
  "lead_time_risk_assessment": {},
  "trade_processing_factor_assessments": {},
  "evidence_refs": [],
  "missing_information": [],
  "follow_up_questions": [],
  "manual_review": {},
  "fallback_supplier": {},
  "pricing_implications": {},
  "audit": {}
}
```

## Status classification

Every material conclusion carries a `status`:

```text
confirmed | inferred | unknown | needs_confirmation
```

The evaluator must never turn inference into fact. Examples:

- If material inventory is not explicitly stated, do not mark it as `confirmed`.
- If a supplier replies slowly, do not automatically classify it as low
  engagement.
- If a supplier replies quickly but gives a precise lead time without material
  evidence, reduce quote confidence or require manual review.

## Sub-assessments

### supplier_execution_assessment
`execution_mode` ∈ `in_house_manufacturer | partial_outsource | trader_or_broker
| assembly_only | material_dependent_manufacturer | unknown`. Carries `status`,
`confidence`, `evidence_refs`, `reasoning_summary`, `alternative_modes`.

### material_availability_assessment
`material_availability_status` ∈ `in_stock | reserved_stock | partial_stock |
supplier_confirmation_required | not_available | substitute_material_required |
unknown`. Plus stock coverage, raw-material confirmation/lead-time fields,
material-lock fields, substitute flag, `status`, `confidence`, `evidence_refs`.

### response_delay_reason_assessment
`most_likely_reason` plus a `probabilities` map over: `material_inventory_check,
raw_material_supplier_confirmation, capacity_check,
subsupplier_process_confirmation, low_engagement, careful_quotation,
timezone_or_holiday, unknown`. Slow response must not automatically become
`low_engagement`; fast response must not automatically become high confidence.

### quote_confidence_assessment
`quote_confidence_level` ∈ `low | medium | high | unknown`, plus
`confidence_score`, `status`, `complete_fields`, `missing_fields`,
`unsupported_claims`, `evidence_refs`.

### lead_time_risk_assessment
`p50_days`, `p80_days`, `p90_days`, `deadline_risk_level` ∈ `low | medium |
medium_high | high | unknown`, `main_risk_drivers`, `p50_drivers`,
`p80_p90_tail_drivers`, and a `risk_decomposition` over twelve risk channels
(engagement, execution control, upstream dependency, material availability,
capacity, process complexity, quality/rework, logistics, customs/compliance,
buyer delay, quote-confidence penalty, lead-time uncertainty).

## Evidence requirements

Evidence refs must point to **input records**, not hallucinated text. Allowed
logical record types:

```text
communication_event_id, behavior_observation_id, supplier_quote_id,
supplier_quote_line_item_id, rfq_id, rfq_line_item_id, procurement_case_id,
supplier_behavior_feature_snapshot_id, buyer_behavior_feature_snapshot_id,
buyer_supplier_behavior_metric_id, operator_confirmed_requirement_id,
manual_input_id
```

Validation rules enforced by GLTG:

- A high-confidence assessment without `evidence_refs` is downgraded.
- A `confirmed` status without `evidence_refs` is invalid (→ `needs_confirmation`).
- If material status is not supported by evidence, status must be `inferred`,
  `unknown`, or `needs_confirmation`.
- An `unknown` value cannot carry a `confirmed` status.

See [validator and guardrails](GLTG_FALLBACK_AND_GUARDRAILS.md).
