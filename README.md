# GLTG — Behavioral + Statistical Lead-Time Graph

`Python 3.11+` | `Current package: GLTG v1.0.0` | `Active model target: gltg-hybrid-v0.1.0` | `FastAPI` | `Deterministic Engine` | `Behavioral Adjustment` | `Statistical Baseline` | `giraffe-db Evidence`

GLTG is the Giraffe Technology lead-time intelligence engine for apparel and textile execution. It answers not only **how many days**, but also **how confident we are**, **which behavior changed the forecast**, **whether a fallback supplier is needed**, and **whether human review is required**.

The current service provides v1 deterministic lead-time, path-enumeration, and reforecast APIs. The active PRD-driven iteration upgrades GLTG into a behavior-aware, statistically calibrated lead-time and risk simulation model.

---

## Current Implementation vs Active Iteration

| Layer | Current status | PRD target |
|---|---|---|
| v1 HTTP API | Implemented | Kept for backward compatibility. |
| v1 lead-time estimate | Implemented | Mapped into v2 output fields where needed. |
| v1 path enumeration | Implemented | Kept and extended with v2 behavior-aware ranking. |
| v1 reforecast | Implemented | Kept and extended with v2 behavioral deltas. |
| v2 `/lead-time/simulate` | In progress / target | Add behavioral + statistical probabilistic simulation. |
| Statistical baseline | In progress / target | Category / route / quantity / supplier / buyer-supplier baseline. |
| Behavioral adjustment layer | In progress / target | Supplier delay, quote completeness, revision behavior, upstream confirmation, buyer volatility, buyer decision delay. |
| ML / Bayesian calibration | Later phase | Add calibration after deterministic explainable MVP. |
| giraffe-db persistence | In progress / target | Persist GLTG runs, behavior inputs, explanation JSON, and source observation references. |

Do not claim v2 production readiness until `/v2/lead-time/simulate`, v2 DTOs, behavior rules, tests, and persistence are implemented and passing.

---

## Product Boundary

The architecture boundary is strict:

```text
facts live in giraffe-db
simulation lives in GLTG
execution lives in AIVAN
```

This means:

```text
giraffe-db = RFQs, quotes, supplier history, lead-time observations, behavior snapshots, source evidence
GLTG      = probabilistic lead-time simulation, behavioral adjustment, risk buffers, explanation JSON
AIVAN     = RFQ execution, supplier/buyer workflow, draft creation, approval gate, operator interface
Human     = final legal/commercial approval
```

GLTG must not store platform credentials, send counterparty messages, approve trade commitments, or invent missing business facts.

---

## Why This Iteration Matters

A simple lead-time calculator mostly adds stage durations:

```text
material days + production days + QC days + logistics days
```

That is not enough for real trade execution.

In real apparel and textile procurement, delivery feasibility changes with behavior:

```text
supplier replies slower than usual
supplier quote is incomplete
supplier revises lead time repeatedly
supplier says material availability is pending
supplier current load is high
buyer keeps changing requirements
buyer delays final decision
buyer-supplier pair historically converts poorly
```

GLTG v2 converts those signals into a probabilistic, explainable forecast:

```text
P50 / P80 / P90
base production days
base procurement days
supplier response buffer
supplier uncertainty buffer
buyer decision buffer
logistics buffer
risk buffer
deadline risk level
fallback supplier recommendation
manual review recommendation
explanation_json
```

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

More specifically:

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

The output is distributional:

```text
P50 = median planning lead time
P80 = conservative planning lead time
P90 = high-confidence planning lead time
```

AIVAN and other consumers should select the confidence level required by the workflow. For example, an urgent buyer-facing commitment may use P80 or P90, while an internal option comparison may inspect P50/P80/P90 together.

---

## Target Model Architecture

```text
RFQ / Quote / PO / Communication Events
        │
        ├── giraffe-db behavior materialization
        │       ├── behavior_observations
        │       ├── buyer_behavior_feature_snapshots
        │       ├── supplier_behavior_feature_snapshots
        │       └── buyer_supplier_behavior_metrics
        │
        ├── GLTG Statistical Baseline
        │       ├── category / route / quantity baseline
        │       ├── supplier historical baseline
        │       ├── buyer-supplier pair baseline
        │       └── leadtime_observations
        │
        ├── GLTG Behavioral Adjustment Layer
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

## Statistical Baseline

The baseline estimates the lead-time distribution before behavioral adjustments.

Minimum baseline hierarchy:

```text
category / route / quantity baseline
supplier historical baseline
buyer-supplier pair baseline
leadtime_observations
```

MVP baseline can be deterministic and explainable. Later calibration may add:

```text
direct quantile regression
AFT / survival baseline
Bayesian hierarchical partial pooling
residual calibration
rolling-origin backtesting
pinball loss optimization
P80/P90 coverage checks
```

The MVP must not block on ML. The first implementation should work with sparse data and clear fallback rules.

---

## Behavioral Feature Set

### Supplier Features

```text
supplier_id
feature_window
current_case_avg_response_seconds
historical_avg_response_seconds
response_delay_ratio
business_hours_delay_ratio
after_hours_response_rate
working_hours_slow_response_rate
quote_completeness_score
missing_quote_fields
quote_revision_count
price_revision_count
lead_time_revision_count
upstream_confirmation_signal
supplier_current_load_signal
engagement_score
quote_response_rate
historical_on_time_delivery_rate
historical_quoted_vs_actual_error_days
lead_time_confidence_score
price_stability_score
```

### Buyer Features

```text
buyer_id
feature_window
current_case_response_latency_seconds
historical_response_latency_seconds
buyer_response_delay_ratio
buyer_decision_delay_score
requirement_change_count
requirement_volatility_score
price_negotiation_intensity
lead_time_sensitivity_score
quality_sensitivity_score
sample_confirmation_delay_score
payment_delay_risk
historical_rounds_to_po
current_case_round_count
conversion_probability
no_response_after_quote_rate
```

### Buyer-Supplier Pair Features

```text
buyer_id
supplier_id
window_type
pair_rfq_count
pair_quote_count
pair_po_count
pair_conversion_rate
avg_rounds_to_po
avg_supplier_response_seconds
avg_buyer_response_seconds
avg_price_gap_vs_buyer_target
avg_leadtime_gap_vs_buyer_target
relationship_strength_score
recommended_pairing_score
dispute_count
quality_issue_count
on_time_delivery_rate
```

---

## MVP Behavioral Rule Table

The first implementation should be deterministic and explainable.

### Supplier Response Delay

```text
response_delay_ratio < 1.2:
  +0 supplier_response_buffer_days
  +0 uncertainty

1.2 <= response_delay_ratio < 2.0:
  +1 supplier_response_buffer_days
  +0.03 Δσ

2.0 <= response_delay_ratio < 3.0:
  +2 supplier_response_buffer_days
  +0.07 Δσ

response_delay_ratio >= 3.0:
  +3 to +5 supplier_response_buffer_days
  +0.12 Δσ
  risk_level +1
  consider fallback supplier
```

### Business-Hours Delay

```text
business_hours_delay_ratio < 1.5:
  no adjustment

1.5 <= business_hours_delay_ratio < 3.0:
  +1 supplier_response_buffer_days

business_hours_delay_ratio >= 3.0:
  +2 supplier_response_buffer_days
  manual_review_if_deadline_tight = true
```

### Quote Completeness

```text
quote_completeness_score >= 0.90:
  no adjustment

0.70 <= quote_completeness_score < 0.90:
  +1 supplier_uncertainty_buffer_days

0.50 <= quote_completeness_score < 0.70:
  +2 supplier_uncertainty_buffer_days
  +0.08 Δσ

quote_completeness_score < 0.50:
  +3 supplier_uncertainty_buffer_days
  +0.15 Δσ
  manual_review_required = true
```

### Quote Revisions

```text
lead_time_revision_count = 0:
  no adjustment

lead_time_revision_count = 1:
  +1 supplier_uncertainty_buffer_days

lead_time_revision_count >= 2:
  +3 supplier_uncertainty_buffer_days
  reduce lead_time_confidence_score
  manual_review_required = true
```

### Upstream Confirmation Signal

```text
upstream_confirmation_signal < 0.3:
  no adjustment

0.3 <= signal < 0.7:
  +1 to +2 supplier_uncertainty_buffer_days

signal >= 0.7:
  +3 supplier_uncertainty_buffer_days
  fallback_supplier_required = true if deadline is tight
```

Examples of upstream dependency signals:

```text
need to ask fabric mill
need material confirmation
waiting for production confirmation
need boss approval
price not confirmed
material availability pending
```

### Buyer Requirement Volatility

```text
requirement_change_count = 0:
  no adjustment

requirement_change_count = 1:
  +1 to +2 buyer_decision_buffer_days

requirement_change_count >= 2:
  +3 to +7 buyer_decision_buffer_days
  increase risk level
```

### Buyer Decision Delay

```text
buyer_decision_delay_score < 0.3:
  no adjustment

0.3 <= score < 0.7:
  +1 to +3 buyer_decision_buffer_days

score >= 0.7:
  +4 to +7 buyer_decision_buffer_days
  pricing service cost buffer recommended
```

---

## Current v1 API

The existing v1 API remains available for compatibility.

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

Version:

```bash
curl http://localhost:8090/version
```

---

## Target v2 API

The PRD target adds behavior-aware v2 endpoints:

```text
POST /v2/lead-time/simulate
POST /v2/paths/enumerate
POST /v2/reforecast
```

Consumers should support:

```bash
GLTG_API_VERSION=v1|v2
```

Default rule during this iteration:

```text
v1 remains default until the standalone GLTG service supports v2.
v2 can be enabled in tests with mock transport.
```

---

## Target v2 Request Schema

```json
{
  "request_id": "REQ_xxx",
  "tenant_id": "tenant_default",
  "source_system": "aivan",
  "source_trace_id": "COMM_xxx",
  "case_context": {
    "procurement_case_id": "GDB_SYN_V1_CASE_000001",
    "rfq_id": "GDB_SYN_V1_RFQ_000001",
    "quote_id": "GDB_SYN_V1_QUOTE_000001",
    "po_id": null,
    "buyer_id": "GDB_SYN_V1_BUYER_000001",
    "supplier_id": "GDB_SYN_V1_SUP_000001"
  },
  "order": {
    "product_category_id": "GDB_SYN_V1_CAT_000001",
    "product_id": null,
    "product_type": "apparel",
    "product_name": "white cotton shirt",
    "quantity": 10000,
    "quantity_unit": "pcs",
    "material": "100% cotton",
    "process_complexity": "standard",
    "customization_level": "medium",
    "destination": "Vancouver",
    "logistics_mode": "sea",
    "deadline_days": 45,
    "target_delivery_date": null,
    "quality_requirement_level": "standard",
    "packaging_requirement_level": "standard"
  },
  "supplier": {
    "supplier_id": "GDB_SYN_V1_SUP_000001",
    "name": "Supplier A",
    "capacity_per_day": 500,
    "material_ready_days": null,
    "production_days": null,
    "qc_days": null,
    "logistics_days": null,
    "supplier_stated_lead_time_days": 28,
    "confidence": 0.7
  },
  "historical_baseline": {
    "baseline_source": "supplier_category_route",
    "sample_size": 48,
    "baseline_p50_days": 32,
    "baseline_p80_days": 39,
    "baseline_p90_days": 45,
    "historical_quoted_vs_actual_error_days": 4.2,
    "on_time_delivery_rate": 0.78
  },
  "behavior_features": {
    "buyer_snapshot_id": "GDB_SYN_V1_BEHAVIOR_000101",
    "supplier_snapshot_id": "GDB_SYN_V1_BEHAVIOR_000102",
    "pair_metric_id": "GDB_SYN_V1_BEHAVIOR_000103",
    "supplier": {
      "response_delay_ratio": 3.0,
      "business_hours_delay_ratio": 2.5,
      "quote_completeness_score": 0.65,
      "lead_time_revision_count": 1,
      "price_revision_count": 0,
      "upstream_confirmation_signal": 0.57,
      "supplier_current_load_signal": 0.68,
      "engagement_score": 0.42
    },
    "buyer": {
      "requirement_change_count": 2,
      "requirement_volatility_score": 0.7,
      "buyer_decision_delay_score": 0.55,
      "price_negotiation_intensity": 0.8,
      "conversion_probability": 0.42
    },
    "pair": {
      "pair_conversion_rate": 0.35,
      "relationship_strength_score": 0.62,
      "recommended_pairing_score": 0.58
    }
  },
  "source_observation_ids": [
    "GDB_SYN_V1_OBS_000001",
    "GDB_SYN_V1_OBS_000002"
  ],
  "constraints": {
    "lead_time_confidence": "P80",
    "fallback_supplier_policy": "recommend_if_risk_high",
    "manual_review_policy": "required_if_deadline_tight",
    "max_acceptable_risk_level": "medium"
  }
}
```

---

## Target v2 Response Schema

```json
{
  "ok": true,
  "gltg_run_id": "GDB_SYN_V1_GLTG_000001",
  "model_version": "gltg-hybrid-v0.1.0",
  "rule_version": "behavior-rules-v0.1.0",
  "calibration_version": "none",
  "quantiles": {
    "p50_days": 38,
    "p80_days": 43,
    "p90_days": 48
  },
  "components": {
    "base_production_days": 28,
    "base_procurement_days": 3,
    "supplier_response_buffer_days": 3,
    "supplier_uncertainty_buffer_days": 2,
    "buyer_decision_buffer_days": 4,
    "logistics_buffer_days": 5,
    "risk_buffer_days": 2
  },
  "risk": {
    "deadline_risk_level": "medium_high",
    "confidence_score": 0.68,
    "fallback_supplier_required": true,
    "manual_review_required": true,
    "deadline_feasible": true,
    "selected_confidence_days": 43
  },
  "explanation_json": {
    "summary": "P80 is recommended because supplier behavior is slower than historical baseline and quote completeness is low.",
    "adjustments": [
      {
        "feature": "supplier_response_delay_ratio",
        "value": 3.0,
        "baseline": "supplier historical average",
        "adjustment": "+3 supplier_response_buffer_days",
        "reason": "Supplier response is 3.0x slower than its historical baseline.",
        "source_observation_ids": ["GDB_SYN_V1_OBS_000001"]
      },
      {
        "feature": "quote_completeness_score",
        "value": 0.65,
        "adjustment": "+2 supplier_uncertainty_buffer_days",
        "reason": "Quote is missing confirmed lead time or material availability.",
        "source_observation_ids": ["GDB_SYN_V1_OBS_000002"]
      }
    ]
  },
  "warnings": [
    {
      "code": "SUPPLIER_RESPONSE_DELAY_ANOMALY",
      "severity": "medium",
      "message": "Supplier current response speed is slower than historical baseline."
    }
  ],
  "persistence": {
    "persisted_to_giraffe_db": true,
    "gltg_behavior_input_id": "GDB_SYN_V1_GLTG_000002"
  }
}
```

---

## v1 to v2 Mapping

When only v1 output exists, consumers may map:

```text
data.p50_days                 → quantiles.p50_days
data.p80_days                 → quantiles.p80_days
data.p90_days                 → quantiles.p90_days
data.risk_level               → risk.deadline_risk_level
data.estimated_lead_time_days → calculated_lead_time_days
data.calculation_trace        → explanation/components source material
```

When v2 output exists, consumers should map:

```text
quantiles.p50_days            → p50_days
quantiles.p80_days            → p80_days
quantiles.p90_days            → p90_days
components.*                  → lead-time components / buffers
risk.deadline_risk_level      → deadline_risk_level
risk.selected_confidence_days → selected_confidence_days
explanation_json              → persisted explanation JSON
gltg_run_id                   → RFQ/project persisted reference
```

---

## AIVAN Integration Requirements

AIVAN should implement:

```text
GLTG_API_VERSION
v2 DTOs
v2 request builder
v2 response parser
v1 compatibility wrapper
mock v2 transport tests
giraffe-db behavior snapshot consumer
source_observation_ids propagation
gltg_run_id persistence
```

AIVAN must not:

```text
calculate lead time locally
silently fall back when GLTG fails
replace GLTG output with LLM guesses
send buyer/supplier messages without human approval
```

---

## giraffe-db Interface Requirements

giraffe-db should provide or materialize:

```text
behavior_observations
buyer_behavior_feature_snapshots
supplier_behavior_feature_snapshots
buyer_supplier_behavior_metrics
leadtime_observations
historical_quotes
supplier_capacity_snapshots
gltg_simulation_runs
gltg_behavior_inputs
pricing_decision_inputs
```

GLTG should preserve source IDs:

```text
source_observation_ids
buyer_snapshot_id
supplier_snapshot_id
pair_metric_id
gltg_run_id
gltg_behavior_input_id
```

Synthetic records from `synthetic_private_v1` must remain clearly labeled as synthetic and must not be represented as real transaction history.

---

## Current v1 Examples

Lead-time estimate:

```bash
curl -s http://localhost:8090/v1/lead-time/estimate \
  -H 'content-type: application/json' \
  -d '{
    "order": {
      "product_type": "apparel",
      "quantity": 10000,
      "target_delivery_date": "2026-08-31",
      "evaluation_date": "2026-06-30",
      "destination": "Vancouver",
      "logistics_mode": "air",
      "deadline_days": 45
    },
    "suppliers": [
      {
        "supplier_id": "M1",
        "name": "Supplier M1",
        "capacity_per_day": 800,
        "material_ready_days": 5,
        "production_days": 14,
        "qc_days": 2,
        "logistics_days": 7,
        "confidence": 0.8
      }
    ],
    "constraints": {
      "allow_partial_suppliers": true,
      "min_supplier_count": 0,
      "currency": "USD"
    }
  }'
```

Path enumeration:

```bash
curl -s http://localhost:8090/v1/paths/enumerate \
  -H 'content-type: application/json' \
  -d '{
    "order": {"product_type": "apparel", "quantity": 10000, "evaluation_date": "2026-06-30"},
    "suppliers": [
      {"supplier_id": "M1", "capacity_per_day": 800, "material_ready_days": 5, "production_days": 14, "qc_days": 2, "logistics_days": 7, "confidence": 0.8},
      {"supplier_id": "M2", "capacity_per_day": 600, "material_ready_days": 4, "production_days": 18, "qc_days": 3, "logistics_days": 8, "confidence": 0.7}
    ],
    "constraints": {"allow_partial_suppliers": true}
  }'
```

Reforecast:

```bash
curl -s http://localhost:8090/v1/reforecast \
  -H 'content-type: application/json' \
  -d '{
    "order": {"product_type": "apparel", "quantity": 10000, "evaluation_date": "2026-06-30"},
    "suppliers": [
      {"supplier_id": "M1", "capacity_per_day": 800, "material_ready_days": 5, "production_days": 14, "qc_days": 2, "logistics_days": 7, "confidence": 0.8}
    ],
    "events": [
      {"supplier_id": "M1", "production_days_delta": 3, "note": "Factory queue delay"}
    ],
    "constraints": {"allow_partial_suppliers": true}
  }'
```

---

## CLI

Evaluate an order:

```bash
gltg evaluate examples/10000_shirts_order.json --summary
```

Write a feasibility packet:

```bash
gltg evaluate examples/10000_shirts_order.json --output packet.json
```

Reforecast an existing serialized packet:

```bash
gltg reforecast packet.json examples/10000_shirts_progress_events.json --summary
```

Important: CLI `reforecast` expects an existing serialized packet as the first argument, not the original order JSON.

Edge cases:

```bash
gltg evaluate examples/zero_suppliers.json --summary
gltg evaluate examples/one_supplier.json --summary
gltg evaluate examples/two_suppliers.json --summary
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
v2 mock transport
behavior rule adjustments
response-delay anomaly
quote completeness adjustment
revision count adjustment
buyer volatility buffer
buyer decision delay buffer
fallback supplier recommendation
manual review trigger
monotonic quantile repair: P50 <= P80 <= P90
v1 backward-compatible mapping
no local fallback in AIVAN
cross-repository contract fixtures
```

---

## Acceptance Criteria for This Iteration

This iteration is accepted when:

1. GLTG keeps v1 endpoints working.
2. GLTG exposes target v2 contract in code and docs.
3. GLTG implements behavior-aware payload parsing.
4. GLTG implements deterministic MVP behavior rules.
5. GLTG produces P50/P80/P90, components, risk, warnings, and explanation JSON.
6. GLTG performs monotonic quantile repair when needed.
7. GLTG surfaces missing baseline or missing behavior data through warnings.
8. GLTG can persist or return `gltg_run_id` and source observation references.
9. AIVAN can call v1 or v2 through `GLTG_API_VERSION`.
10. AIVAN does not calculate lead time locally.
11. AIVAN does not silently fall back when GLTG fails.
12. Tests pass for v1 regression and v2 behavior-specific cases.

---

## Implementation Phases

### Phase 0 — Documentation

```text
Document the behavioral + statistical GLTG PRD.
Rewrite README around v1 compatibility + v2 target architecture.
```

### Phase 1 — AIVAN Client Contract

```text
GLTG_API_VERSION
v2 DTOs
v2 request builder
v2 response parser
v1 compatibility wrapper
mock fixture tests
```

### Phase 2 — AIVAN giraffe-db Feature Integration

```text
read buyer behavior snapshot
read supplier behavior snapshot
read buyer-supplier pair metrics
read leadtime observations
include source_observation_ids
```

### Phase 3 — AIVAN RFQ Flow Integration

```text
RFQ creation
supplier quote parsing
buyer option generation
supplier fallback recommendation
manual review logic
pricing input generation
```

### Phase 4 — Standalone GLTG Service

```text
/v2/lead-time/simulate
statistical baseline
behavior adjustment rule engine
fallback composer
explanation_json
giraffe-db persistence of gltg_simulation_runs
```

### Phase 5 — abcdYi / giraffe-agent Port

```text
copy shared contract and adapters into abcdYi and giraffe-agent
keep GLTG as calculation authority
```

### Phase 6 — Statistical / ML Calibration

```text
rolling-origin backtest
pinball loss
P80/P90 coverage
quantile crossing repair
Bayesian / hierarchical calibration
residual calibration
```

---

## Metrics and Backtesting

Forecast accuracy metrics:

```text
MAE for P50
pinball loss for P80/P90
P80 coverage
P90 coverage
deadline miss false-negative rate
fallback recommendation precision
manual review trigger precision
```

Operational metrics:

```text
RFQ cycle-time reduction
supplier response delay detection rate
buyer decision delay detection rate
quote completeness improvement
fallback supplier usage rate
operator override rate
```

Data readiness thresholds:

```text
>= 30 observations for category/route baseline
>= 10 observations for supplier baseline
>= 5 observations for buyer-supplier pair baseline
fallback mode required below threshold
```

---

## Risk Controls

### Semantic Risk

LLMs may misread supplier messages. GLTG should only consume structured features and source IDs produced by upstream extraction and validation.

### Data Quality Risk

Sparse or synthetic data must be flagged. Missing data should trigger fallback mode, warnings, and manual review where appropriate.

### Black-Box Risk

The MVP must be rule-based and explainable. ML calibration should not remove explanation JSON or source traces.

### Product Boundary Risk

AIVAN must not perform hidden GLTG math. GLTG must not send messages or make commercial commitments.

---

## Install and Run

Install:

```bash
git clone https://github.com/GiraffeTechnology/GLTG.git
cd GLTG
python -m pip install -e ".[dev]"
```

API-only runtime:

```bash
python -m pip install -e ".[api]"
```

Run API:

```bash
uvicorn gltg.api.main:app --host 0.0.0.0 --port 8090
```

Docker:

```bash
docker build -t giraffe-gltg .
docker run -p 8090:8090 giraffe-gltg
```

---

## Documentation

| Doc | Description |
|---|---|
| `docs/model_spec.md` | Existing GLTG model specification. |
| `docs/evidence_weighting.md` | Evidence hierarchy and weighting. |
| `docs/apparel_node_templates.md` | Apparel node templates. |
| `docs/path_enumeration.md` | Path enumeration algorithm. |
| `docs/reforecasting.md` | Reforecast after progress events. |
| `docs/integration_guide.md` | Consumer integration guide. |
| `docs/api_reference.md` | HTTP API reference. |
| `docs/acceptance_criteria.md` | v1.0 acceptance criteria. |
| `docs/glossary.md` | Terminology glossary. |

A dedicated behavioral/statistical PRD should also be kept in `docs/` when the implementation PR is opened in this repository.

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

That is the difference between a simple lead-time calculator and a Giraffe-grade procurement intelligence model.

---

## License

See `LICENSE`.
