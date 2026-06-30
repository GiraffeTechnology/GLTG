# GLTG Trade Processing Time Factor Model

> **Status update — provider-agnostic LLM-assisted evaluator.**
> GLTG's primary v2 model is now a **provider-agnostic LLM-assisted trade
> lead-time risk evaluator** (Qwen3.5 default, mainstream-LLM compatible via a
> provider adapter interface). See
> [GLTG_PROVIDER_AGNOSTIC_LLM_ASSISTED_TRADE_RISK_EVALUATOR.md](GLTG_PROVIDER_AGNOSTIC_LLM_ASSISTED_TRADE_RISK_EVALUATOR.md).
>
> The trade/processing factors and deterministic formulas described below are
> **no longer the primary GLTG intelligence layer**. They are retained as the
> request vocabulary the LLM evaluator consumes, and as deterministic
> guardrails / sanity checks / optional fallback only
> (`src/gltg/evaluator/fallback_rules.py`, used when
> `GLTG_EVALUATOR_MODE=fallback` or an allowed provider-failure fallback). The
> default `/v2/lead-time/simulate` path does **not** use these formulas as the
> primary evaluator.

This document captures the GLTG v2 trade and processing factor vocabulary and
the deterministic fallback layer.

## Objective

GLTG must distinguish:

```text
execution ability
material availability
behavioral response pattern
```

Supplier response speed is a signal, not a direct risk score. Slow response can mean material confirmation or careful quoting. Fast response can be low quality when it includes a precise lead time without material evidence.

## Request Extension

`GLTGSimulationRequestV2.trade_processing_factors` contains:

```text
requirement
supplier_execution
material
processing
logistics_trade
behavior
```

Material statuses:

```text
in_stock
reserved_stock
partial_stock
supplier_confirmation_required
not_available
substitute_material_required
unknown
```

Response-delay reasons:

```text
material_inventory_check
raw_material_supplier_confirmation
capacity_check
subsupplier_process_confirmation
low_engagement
careful_quotation
timezone_or_holiday
unknown
```

## Implemented Formulas

Material availability risk:

```text
0.25 * status_risk(material_availability_status)
+ 0.20 * (1 - material_availability_confidence)
+ 0.20 * raw_material_supplier_confirmation_probability
+ 0.15 * raw_material_lead_time_uncertainty_score
+ 0.10 * substitute_material_probability
+ 0.10 * historical_material_delay_rate
```

Execution control score:

```text
0.35 * in_house_capability_confidence
+ 0.20 * historical_on_time_delivery_rate
+ 0.15 * quote_completeness_score
+ 0.15 * material_availability_confidence
+ 0.15 * (1 - upstream_dependency_probability)
```

Upstream dependency probability:

```text
0.25 * explicit_upstream_signal
+ 0.20 * raw_material_supplier_confirmation_probability
+ 0.15 * missing_material_status
+ 0.10 * trader_score
+ 0.10 * external_subprocess_dependency_score
+ 0.10 * quote_revision_frequency_score
+ 0.05 * response_delay_ratio_score
+ 0.05 * historical_leadtime_error_score
```

Lead-time uncertainty risk:

```text
0.18 * material_availability_risk
+ 0.16 * upstream_dependency_risk
+ 0.14 * execution_control_risk
+ 0.12 * capacity_risk
+ 0.10 * process_complexity_risk
+ 0.10 * quality_rework_risk
+ 0.10 * logistics_risk
+ 0.08 * customs_compliance_risk
+ 0.07 * buyer_delay_risk
+ 0.05 * quote_confidence_penalty
```

Trade factor composer:

```text
P50 = baseline P50 + central trade/process shift
P80 = P50 + base_spread * (1 + 0.8 * lead_time_uncertainty_risk)
P90 = P50 + base_spread * (1 + 1.3 * lead_time_uncertainty_risk)
```

## Response Extension

Responses include:

```text
components.requirement_confirmation_days
components.material_confirmation_days
components.material_procurement_days
components.capacity_queue_days
components.production_days
components.expected_rework_days
components.departure_wait_days
risk_decomposition.*
response_delay_reason_inference.*
explanation_json.trade_processing_factor_scores
```

## DB Mapping

Fields map to `giraffe-db` without requiring product repositories to copy model logic:

```text
behavior_observations.behavior_type
supplier_behavior_feature_snapshots.feature_json
gltg_behavior_inputs.feature_json
optional material_availability_observations
```

Supported behavior observation types include material stock signals, material supplier confirmation required, capacity check signal, production schedule check signal, careful quotation signal, low-quality fast quote signal, unsupported precise lead-time signal, and subsupplier process confirmation required.

## Required Scenario Coverage

The test suite covers:

```text
fast response + material in stock
slow response + factory + material supplier confirmation
fast response + no material evidence + precise lead time
trader + material pending
formula output determinism and P50/P80/P90 monotonicity
```
