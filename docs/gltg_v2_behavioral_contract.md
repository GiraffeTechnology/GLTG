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

The API exposes `model_version`, `rule_version`, `calibration_version`, `gltg_run_id`, `components`, `risk`, `explanation_json`, and lineage fields so future statistical/Bayesian calibration can replace the internal composer without breaking product clients.
