# GLTG v2 Behavioral Simulation Contract

GLTG v2 is the standalone API boundary for behavior-aware probabilistic lead-time simulation.

Product repositories (`aivan`, `abcdYi`, `giraffe-agent`) must call GLTG over HTTP and must not copy the simulation math, behavioral rule engine, or local fallback composer into product code.

## Endpoints

```text
POST /v2/lead-time/simulate
POST /v2/paths/enumerate
POST /v2/reforecast
```

Existing v1 endpoints remain available for migration compatibility.

## Contract Fixtures

Shared cross-repo fixtures live in:

```text
tests/fixtures/gltg_v2_simulation_request.json
tests/fixtures/gltg_v2_simulation_response.json
```

These files define the canonical request and response field names for downstream client adapters.

## Trade Processing Factor Layer

`GLTGSimulationRequestV2` now accepts an optional `trade_processing_factors` object. This is the first-class boundary for trade, manufacturing, raw material, logistics, and communication features that affect lead time.

Top-level factor groups:

```text
requirement
supplier_execution
material
processing
logistics_trade
behavior
```

The model treats supplier response speed as a behavior signal, not a direct risk score. GLTG must infer whether slow response is more likely caused by material inventory checking, raw material supplier confirmation, capacity checking, low engagement, careful quotation, timezone/holiday effects, or unknown causes.

Fast response is also not automatically good. A fast precise quote with unknown or supplier-confirmation-required material status and no supporting material evidence can reduce `quote_confidence_score` and trigger manual review.

## Extended v2 Response

When `trade_processing_factors` are present, GLTG uses the `trade_processing_factor_spread` composer:

```text
P50 = baseline P50 + central trade/process shift
P80 = P50 + base spread widened by lead_time_uncertainty_risk
P90 = P50 + stronger tail widening from lead_time_uncertainty_risk
```

Responses include:

```text
components.requirement_confirmation_days
components.material_confirmation_days
components.material_procurement_days
components.capacity_queue_days
components.production_days
components.departure_wait_days
risk_decomposition.material_availability_risk
risk_decomposition.upstream_dependency_risk
risk_decomposition.execution_control_risk
risk_decomposition.lead_time_uncertainty_risk
response_delay_reason_inference.most_likely_reason
response_delay_reason_inference.probabilities
explanation_json.trade_processing_factor_scores
```

Without `trade_processing_factors`, existing v2 requests keep the previous behavioral composer behavior.

## Responsibility Boundary

```text
facts live in giraffe-db
simulation lives in GLTG
execution lives in product repositories
```

Clients may:

```text
build v2 payloads
pass behavior snapshot IDs and source observation IDs
validate and map responses
surface structured GLTG errors
store GLTG run references
```

Clients must not:

```text
calculate lead time locally
silently fall back to local estimates
invent behavior facts with an LLM
copy GLTG behavioral rules into product code
```

## MVP Model

The current implementation is an explainable rule-based MVP with two composers:

When historical quantiles are available:

```text
pseudo-lognormal baseline
+ central behavior shift
+ sigma inflation
+ tail uncertainty buffers
=> monotonic P50/P80/P90
```

When historical quantiles are unavailable:

```text
deterministic fallback baseline
+ supplier response buffer
+ supplier uncertainty buffer
+ buyer decision buffer
+ risk buffer
=> monotonic P50/P80/P90
```

When trade and processing factors are available:

```text
stage component baseline
+ material availability and procurement signals
+ execution-control and upstream-dependency formulas
+ processing, capacity, logistics, customs, and buyer delay factors
+ response-delay reason inference
=> separated P50 central shift and P80/P90 uncertainty widening
```

The API exposes `model_version`, `rule_version`, `calibration_version`, `gltg_run_id`, `components`, `risk`, `explanation_json`, and lineage fields so future statistical/Bayesian calibration can replace the internal composer without breaking product clients.

## DB Mapping

The implementation keeps storage outside GLTG for now, but the contract maps cleanly to `giraffe-db`:

```text
behavior_observations.behavior_type
supplier_behavior_feature_snapshots.feature_json
gltg_behavior_inputs.feature_json
optional material_availability_observations
```

GLTG responses preserve `source_observation_ids`, behavior snapshot IDs, `gltg_run_id`, and factor scores so giraffe-db can persist lineage without product repositories copying the model.
