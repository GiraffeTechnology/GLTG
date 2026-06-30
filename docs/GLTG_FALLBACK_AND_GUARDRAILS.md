# GLTG Fallback and Guardrails

Deterministic rules are **not** the primary GLTG model. They are retained only
as validators, guardrails, sanity checks, test baselines, and optional fallback.

## Validator (`src/gltg/evaluator/validator.py`)

Runs after every provider result:

- schema validity (typed packet parse; invalid → repair pass → manual review)
- `P50 <= P80 <= P90`, all positive
- status enum validity
- risk-decomposition values clipped to `[0, 1]`
- response-delay-reason probabilities clipped to `[0, 1]`, renormalized if the
  sum drifts beyond tolerance
- `confirmed` status requires `evidence_refs` (else → `needs_confirmation`)
- high confidence requires `evidence_refs` (else downgraded)
- `unknown` value cannot carry a `confirmed` status
- missing material status cannot produce high quote confidence without evidence

On unrecoverable failure the validator never emits an invalid packet: the
orchestrator returns a manual-review assessment.

## Guardrails (`src/gltg/evaluator/guardrails.py`)

PRD business invariants applied after validation:

- **Fast unsupported quote** — fast response + precise lead time + no material
  evidence → quote-confidence penalty and manual review
  (`UNSUPPORTED_FAST_PRECISE_QUOTE`).
- **Slow material confirmation** — slow response + material-supplier evidence is
  reclassified away from `low_engagement`
  (`SLOW_RESPONSE_NOT_LOW_ENGAGEMENT`).
- **Deadline consistency** — if a hard target is provided and `P80` exceeds it,
  `deadline_risk_level` cannot be `low` (`DEADLINE_RISK_INCONSISTENT`).

## Quantile normalizer

The LLM may recommend `P50/P80/P90`, but GLTG owns normalization:

- enforce `P50 <= P80 <= P90` with a minimum spread
- `P50` is not pushed below a confirmed supplier-stated lead time unless
  evidence justifies it
- widen `P80/P90` tails (not necessarily `P50`) when material availability is
  `unknown` / `supplier_confirmation_required` / `not_available`, when upstream
  dependency is high, or when quote confidence is low

## Fallback rules (`src/gltg/evaluator/fallback_rules.py`)

The legacy hard-coded behavioral formulas were moved here and demoted. They run
only when:

- `GLTG_EVALUATOR_MODE=fallback`, **or**
- `GLTG_EVALUATOR_MODE=llm` **and** the provider fails **and**
  `GLTG_ALLOW_RULE_FALLBACK=true`.

When the fallback is used because a provider was unavailable, the response
includes:

```json
{
  "evaluation_mode": "fallback",
  "warnings": [
    {"code": "LLM_PROVIDER_UNAVAILABLE_RULE_FALLBACK_USED", "severity": "medium"}
  ]
}
```

If fallback is **not** allowed, GLTG returns `manual_review_required=true` and an
`EVALUATOR_UNAVAILABLE` warning — it does not invent a model result.

## Tests

- `tests/evaluator/test_validator_guardrails.py` — validator/guardrail/normalizer
- `tests/evaluator/test_no_hardcoded_primary.py` — proves the rule simulator is
  never the primary evaluator
- `tests/api/test_v2_behavioral_simulation.py` — legacy formula regressions, run
  with `GLTG_EVALUATOR_MODE=fallback`
