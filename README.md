# GLTG — Behavioral + Statistical Lead-Time Graph

`Python 3.11+` | `Current package: GLTG v1.0.0` | `Active model target: gltg-hybrid-v0.1.0` | `FastAPI` | `Deterministic Engine` | `Behavioral Adjustment` | `Statistical Baseline` | `giraffe-db Evidence`

GLTG is the Giraffe Technology lead-time intelligence engine for apparel and textile execution.

It answers not only **how many days**, but also **how confident we are**, **which behavior changed the forecast**, **whether a fallback supplier is needed**, and **whether human review is required**.

The current service provides v1 deterministic lead-time, path-enumeration, and reforecast APIs. The active PRD-driven iteration upgrades GLTG into a behavior-aware, statistically calibrated lead-time and risk simulation model.

---

## Current Implementation vs Active Iteration

| Layer | Current status | PRD target |
|---|---|---|
| v1 HTTP API | Implemented | Kept for backward compatibility. |
| v1 lead-time estimate | Implemented | Mapped into v2 output fields where needed. |
| v1 path enumeration | Implemented | Extended with behavior-aware ranking. |
| v1 reforecast | Implemented | Extended with behavioral deltas. |
| v2 `/v2/lead-time/simulate` | Target / in progress | Behavioral + statistical probabilistic simulation. |
| Statistical baseline | Target / in progress | Category / route / quantity / supplier / buyer-supplier baselines. |
| Behavioral adjustment layer | Target / in progress | Supplier and buyer behavior features. |
| giraffe-db persistence | Target / in progress | Persist runs, inputs, explanations, and source observation IDs. |
| ML / Bayesian calibration | Later phase | Add after explainable deterministic MVP. |

Do not claim v2 production readiness until v2 DTOs, rule engine, persistence, and tests are implemented and passing.

---

## System Boundary

```text
giraffe-language-skill = canonical English language boundary
giraffe-db             = private business facts and source evidence
GLTG                   = lead-time simulation and risk forecast
GPM                    = procurement graph reasoning
AIVAN / giraffe-agent  = execution workflow and human approval
```

GLTG does not own channel connectivity, multilingual extraction, RFQ/project state, private database ownership, QC inference, outbound messages, or legal/commercial approval.

---

## P0 Language Boundary

Standard English is the only internal working language across Giraffe products.

GLTG must consume canonical English structured payloads. It must not extract business facts directly from raw multilingual buyer, supplier, or operator messages.

Input path:

```text
raw multilingual text
-> giraffe-language-skill
-> canonical English business packet
-> giraffe-db evidence / AIVAN request builder
-> GLTG simulation
```

GLTG may preserve language metadata and source observation IDs, but lead-time simulation must run on canonical structured fields.

---

## Core Model Concept

GLTG v2 models total planning lead time as:

```text
Total Planning Lead Time
= Base Lead-Time Distribution
+ Behavioral Central Shift
+ Behavioral Uncertainty Inflation
+ Fallback / Risk Guardrails
```

Expanded planning model:

```text
T_total
= T_requirement_confirmation
+ T_supplier_response
+ T_quote_confirmation
+ T_material_procurement
+ T_production
+ T_qc
+ T_logistics
+ T_buyer_decision
+ T_risk_buffer
```

Distributional output:

```text
P50 = median planning lead time
P80 = conservative planning lead time
P90 = high-confidence planning lead time
```

---

## Target Model Architecture

```text
Canonical RFQ / Quote / PO / Communication Events
        │
        ├── giraffe-db behavior materialization
        │       ├── behavior_observations
        │       ├── buyer_behavior_feature_snapshots
        │       ├── supplier_behavior_feature_snapshots
        │       └── buyer_supplier_behavior_metrics
        │
        ├── Statistical Baseline
        │       ├── category / route / quantity baseline
        │       ├── supplier historical baseline
        │       ├── buyer-supplier pair baseline
        │       └── leadtime_observations
        │
        ├── Behavioral Adjustment Layer
        │       ├── supplier response delay anomaly
        │       ├── quote completeness
        │       ├── revision behavior
        │       ├── upstream dependency signal
        │       ├── current load signal
        │       ├── buyer decision delay
        │       └── buyer requirement volatility
        │
        ├── Hybrid Quantile Composer
        │       ├── P50
        │       ├── P80
        │       └── P90
        │
        ├── Explainable Fallback Guard
        │       ├── missing baseline handling
        │       ├── missing behavior handling
        │       ├── monotonic quantile repair
        │       └── manual review triggers
        │
        └── Persisted GLTG run
                ├── gltg_run_id
                ├── model_version
                ├── rule_version
                ├── explanation_json
                └── source_observation_ids
```

---

## Behavioral Feature Inputs

Supplier features:

```text
response_delay_ratio
business_hours_delay_ratio
quote_completeness_score
missing_quote_fields
quote_revision_count
lead_time_revision_count
upstream_confirmation_signal
supplier_current_load_signal
historical_on_time_delivery_rate
historical_quoted_vs_actual_error_days
lead_time_confidence_score
```

Buyer features:

```text
requirement_change_count
requirement_volatility_score
buyer_decision_delay_score
buyer_response_delay_ratio
price_negotiation_intensity
historical_rounds_to_po
conversion_probability
```

Buyer-supplier pair features:

```text
pair_conversion_rate
avg_rounds_to_po
avg_supplier_response_seconds
avg_buyer_response_seconds
relationship_strength_score
recommended_pairing_score
dispute_count
quality_issue_count
on_time_delivery_rate
```

Behavior signals are risk signals, not hard facts. High-impact adjustments must be explained in `explanation_json`.

---

## Current v1 API

```text
GET  /health
GET  /version
POST /v1/lead-time/estimate
POST /v1/paths/enumerate
POST /v1/reforecast
```

Run service:

```bash
uvicorn gltg.api.main:app --host 0.0.0.0 --port 8090
```

Health:

```bash
curl http://localhost:8090/health
```

---

## Target v2 API

```text
POST /v2/lead-time/simulate
POST /v2/paths/enumerate
POST /v2/reforecast
```

Expected v2 response fields:

```text
gltg_run_id
model_version
rule_version
calibration_version
quantiles.p50_days
quantiles.p80_days
quantiles.p90_days
components.base_production_days
components.base_procurement_days
components.supplier_response_buffer_days
components.supplier_uncertainty_buffer_days
components.buyer_decision_buffer_days
components.logistics_buffer_days
components.risk_buffer_days
risk.deadline_risk_level
risk.confidence_score
risk.fallback_supplier_required
risk.manual_review_required
risk.deadline_feasible
risk.selected_confidence_days
explanation_json
warnings
persistence
source_observation_ids
```

---

## Supplier Count Rules

GLTG must never crash or invent suppliers to fill comparison slots.

| Supplier count | Behavior |
|---:|---|
| `0` | Return infeasible result with `NO_SUPPLIERS`; no crash. |
| `1` | Calculate with limited-comparison warning. |
| `2` | Calculate with limited-supplier-pool warning. |
| `3+` | Run normal comparison and path enumeration. |

---

## Tests

Current tests:

```bash
pytest
python scripts/verify_gltg_5x.py
python scripts/run_zero_one_two_supplier_cases.py
python scripts/run_10000_shirts_acceptance.py
python scripts/run_api_edge_cases.py
```

v2 iteration must add tests for:

```text
v2 DTO validation
behavior rule adjustments
response-delay anomaly
quote completeness adjustment
revision count adjustment
buyer volatility buffer
buyer decision delay buffer
fallback supplier recommendation
manual review trigger
monotonic quantile repair: P50 <= P80 <= P90
missing baseline warnings
source observation trace preservation
v1 backward-compatible mapping
```

---

## Acceptance Criteria

This iteration is accepted when:

1. v1 endpoints remain working.
2. v2 contract exists in code and docs.
3. behavior-aware payload parsing works.
4. deterministic MVP behavior rules work.
5. P50/P80/P90, components, risk, warnings, and explanation JSON are returned.
6. monotonic quantile repair is enforced.
7. missing baseline or missing behavior data produces warnings.
8. source observation IDs and GLTG run IDs are preserved.
9. AIVAN and giraffe-agent can select v1 or v2 without local fallback.
10. LLMs do not replace GLTG calculations.

---

## Install

```bash
git clone https://github.com/GiraffeTechnology/GLTG.git
cd GLTG
python -m pip install -e ".[dev]"
```

API-only runtime:

```bash
python -m pip install -e ".[api]"
```

Docker:

```bash
docker build -t giraffe-gltg .
docker run -p 8090:8090 giraffe-gltg
```

---

## Final Product Principle

GLTG must not answer only:

```text
How many days?
```

It must answer:

```text
How many days at P50 / P80 / P90?
Why?
Which buyer/supplier behavior changed the forecast?
How confident are we?
Do we need a fallback supplier?
Do we need manual review?
Should pricing add risk buffer?
```

---

## License

See `LICENSE`.
