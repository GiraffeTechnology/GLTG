# GLTG — Behavioral + Statistical Lead-Time Graph

`Python 3.11+` | `Current package: GLTG v1.0.0` | `Active model: gltg-hybrid-v0.1.0` | `FastAPI` | `Deterministic Engine`

GLTG is the Giraffe Technology lead-time intelligence engine for apparel and textile execution.

It answers not only **how many days**, but also **how confident we are**, **which behavior changed the forecast**, **whether a fallback supplier is needed**, and **whether human review is required**.

---

## Implementation Status (audited — Stage 3)

Statuses: **implemented** (tested, executable), **experimental** (works, opt-in,
not production-validated), **planned**, **not implemented**.

| Layer | Status |
|---|---|
| v1 HTTP API (estimate / paths / reforecast) | implemented (deterministic graph engine) |
| v2 `/v2/lead-time/simulate` | implemented — deterministic rule engine is the default; every nonzero adjustment is explained |
| v2 `/v2/paths/enumerate` | implemented (ranks per-supplier simulations; never invents suppliers) |
| v2 `/v2/reforecast` | implemented (applies typed events; discloses previous quantiles, delta, changed components) |
| giraffe-db evidence retrieval (supplier record + behavior summary, tenant-scoped, fail-closed) | implemented — explicit opt-in per request (`evidence.use_giraffe_db`) |
| giraffe-db run persistence (`gltg_simulation_runs`) | implemented — opt-in (`GLTG_PERSIST_RUNS`), truthful `persistence.status` |
| Statistical baseline | partial — caller-supplied historical P50/P80/P90 is consumed; category/route/pair baseline retrieval is planned |
| LLM-assisted evaluation (`GLTG_EVALUATOR_MODE=llm`) | experimental — strictly explicit opt-in; never the default; never silent |
| ML / Bayesian calibration | not implemented (`calibration_version="none"`) |

Production-readiness caveats are tracked in
`docs/stage3/STAGE3_FINAL_VALIDATION.md`. Model accuracy has **not** been
validated against real transaction data — all validation used the synthetic
`GDB_SYN_V1` dataset, and outputs based on it must not be represented as real
history.

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

## API

```text
GET  /health      # process alive
GET  /ready       # dependency readiness (evaluator mode, giraffe-db) — no secrets
GET  /version
POST /v1/lead-time/estimate
POST /v1/paths/enumerate
POST /v1/reforecast
POST /v2/lead-time/simulate
POST /v2/paths/enumerate
POST /v2/reforecast
```

Run service:

```bash
export GLTG_INBOUND_SERVICE_AUTH_SECRET='replace-with-secret-manager-value'
uvicorn gltg.api.main:app --host 0.0.0.0 --port 8090
```

Every v2 request requires authenticated service headers. `tenant_id` is
mandatory in the JSON body and must exactly match the authenticated tenant;
the body never selects tenant identity.

```text
X-Service-Auth: <GLTG_INBOUND_SERVICE_AUTH_SECRET>
X-Service-Tenant-ID: <authenticated-tenant>
```

### giraffe-db evidence and persistence

giraffe-db is the canonical evidence service. Configure:

```bash
GLTG_GIRAFFE_DB_BASE_URL=http://giraffe-db:8000
GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET=...   # sent as X-Service-Auth, never logged
GLTG_PERSIST_RUNS=true                    # optional run persistence
```

A v2 request with `"evidence": {"use_giraffe_db": true}` retrieves the
tenant-scoped supplier record and behavior summary
(`X-Service-Tenant-ID` = request `tenant_id`). A configured giraffe-db URL
without a service-auth secret fails before transport, and every supplier,
behavior-summary, and persistence response must echo the same tenant. Failures are explicit:
unreachable giraffe-db → HTTP 503 `DB_UNAVAILABLE`; rejected auth/tenant →
HTTP 502 `EVIDENCE_AUTH_FAILED` (fail closed); missing supplier/behavior →
`EVIDENCE_NOT_FOUND` / `MISSING_BEHAVIOR_EVIDENCE` warnings with reduced
confidence. GLTG never invents evidence and has no silent mock fallback.
End-to-end proof: `scripts/validate_gltg_giraffe_db_e2e.py`.

### v2 response fields:

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
python scripts/validate_gltg_giraffe_db_e2e.py   # requires a giraffe-db checkout
```

Stage 3 invariant/property/integration tests live under `tests/stage3/`:
quantile monotonicity, non-negative days, confidence bounds, determinism
(same input + same versions = identical output), 0/1/2/3+ supplier behavior,
monotone response to worsening evidence, v2 response contract, giraffe-db
auth/tenant/timeout behavior, truthful persistence status, and typed
reforecast events. The rule inventory is
`docs/stage3/gltg_rule_inventory.json`.

---

## Acceptance Criteria

Status per Stage 3 validation (`docs/stage3/STAGE3_FINAL_VALIDATION.md`):

1. v1 endpoints remain working — **met**.
2. v2 contract exists in code and docs — **met**.
3. behavior-aware payload parsing works — **met**.
4. deterministic MVP behavior rules work (and are the default) — **met**.
5. P50/P80/P90, components, risk, warnings, and explanation JSON are returned — **met**.
6. monotonic quantile repair is enforced — **met** (tested invariant).
7. missing baseline or missing behavior data produces warnings — **met**.
8. source observation IDs and GLTG run IDs are preserved — **met** (never invented).
9. AIVAN and giraffe-agent can select v1 or v2 without local fallback — consumer-side, unverified here.
10. LLMs do not replace GLTG calculations — **met**: the deterministic engine is the default; LLM mode is explicit opt-in only.

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
