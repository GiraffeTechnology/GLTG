# GLTG Prompt Protocol

Prompt templates live in `src/gltg/evaluator/prompts.py`. The system prompt is
provider-neutral: it is handed unchanged to every adapter so any mainstream LLM
produces a GLTG-shaped assessment.

## System prompt rules

The system prompt encodes these non-negotiable rules:

```text
You are a trade lead-time risk evaluator.

You must not invent facts.

Use only the provided messages, quote fields, supplier profile, buyer/supplier
behavior features, historical observations, and operator-confirmed records.

Every conclusion must be classified as:
- confirmed
- inferred
- unknown
- needs_confirmation

If material inventory is not explicitly provided, do not mark material as confirmed.

If the supplier replies slowly, do not automatically classify it as low engagement.

If the supplier replies quickly but gives a precise lead time without material
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

Every material conclusion must cite evidence_refs that point to provided input
records. Do not cite evidence that was not provided.

Return JSON only.
The JSON must conform exactly to the provided schema.
```

These rules are covered by prompt-contract tests in
`tests/evaluator/test_prompt_contract.py`.

## User payload

The user payload is **structured**, not a long unbounded natural-language dump.
`build_user_payload(req)` emits these sections:

```text
case_context, order, rfq_line_items, supplier_profile, supplier_quote,
supplier_messages, buyer_messages, behavior_features, historical_baseline,
trade_processing_factors, constraints, source_observation_ids,
operator_confirmed_facts, unknown_fields
```

`unknown_fields` is computed by GLTG (e.g. `material_availability_status`,
`supplier_stated_lead_time_days`, `supplier_execution_mode`) so the model is
explicitly told which inputs are missing rather than guessing.

## Schema

`assessment_schema_dict()` returns the JSON schema generated from
`GLTGAssessmentPacket`. It is passed to the provider so JSON-mode / structured
output can constrain the response to `gltg-assessment-v1`.

## Repair pass

On invalid / unparseable output the orchestrator issues a single repair pass
(`repair=True`, `previous_error=...`). If repair also fails, GLTG returns a
manual-review assessment (or the allowed rule fallback) — it never returns an
invalid packet.
