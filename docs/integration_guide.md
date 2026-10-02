# GLTG API integration guide

## Supported product boundary

Aivan calls GLTG as an API dependency for inquiry, quotation and order-confirmation decisions. abcdYi and Giraffe Agent use the same model ownership boundary. The GLTG service owns its engine, model formulas, evaluator and permitted fallbacks. Product clients build requests, map responses and expose dependency errors; they do not import `LeadTimeGraphEngine`, manipulate `sys.path` to embed it, or copy model logic as a local fallback.

The earlier embedded-engine integration recipe is preserved in the source revision history as a legacy reference. Its implementation and provider-side utilities are not deleted by this documentation update.

## Existing endpoints

The v1 consumer interface includes:

```text
GET  /health
GET  /version
POST /v1/lead-time/estimate
POST /v1/paths/enumerate
POST /v1/reforecast
```

The v2 model interface includes:

```text
POST /v2/lead-time/simulate
POST /v2/paths/enumerate
POST /v2/reforecast
```

Keep current request/response names in `api_reference.md`, `gltg_v2_behavioral_contract.md` and the versioned contract fixtures. This documentation update does not rename protocol identifiers or claim that all clients already use v2.

## Facts and language

Build model input from the selected replaceable private DB. Include relevant historical baselines and current process evidence, identifiers, behavior snapshots and source observation IDs. `giraffe-db` is the reference provider; a compatible user-owned DB may be substituted without redefining GLTG or Aivan.

Non-English input must pass through `giraffe-language-skill` before the business workflow and model call. GLTG receives standard-English business packets. The DB stores English business history, process records and results, with only enterprise/user profile information permitted to retain non-English values. Raw/evidence/audit fields do not create further exceptions.

## Provider authentication and persistence

The current GLTG reference data client is `src/gltg/integrations/giraffe_db_client.py`. Its existing settings are `GLTG_GIRAFFE_DB_BASE_URL`, `GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET` and `GLTG_GIRAFFE_DB_TIMEOUT_SECONDS`. A verified tenant ID is passed per call using `X-Service-Tenant-ID`; the service credential uses `X-Service-Auth`. Preserve these security properties when mapping a replacement provider.

Persist required run inputs, outputs, model/rule/calibration versions, explanations and source IDs through the selected private DB. A successful model calculation does not prove that a later write succeeded. Report missing facts, invalid credentials, unavailable storage and failed persistence accurately. Do not substitute conversation memory for DB-backed evidence.

## Model results

Preserve P50/P80/P90 quantiles, component durations, risk decomposition, response-delay interpretation, explanations, warnings and lineage. Do not turn a planning estimate into a verified commercial guarantee. Preserve supplier-provided quotes and facts separately from model-derived interpretation.

An LLM provider failure and a DB evidence failure are different conditions. Any supported GLTG-internal fallback remains explicit in response metadata and warnings. Clients do not silently replace a failed API response with a local calculation or invented data.

## Verification

Use the owner's designated simulated databases for legitimate product acceptance, with accurate synthetic labels. Exercise the actual selected consumer, GLTG service and data-provider path: requests and headers, successful and failing responses, relevant business read/write/readback, and traceability. Report test doubles and skipped/unexecuted integration stages separately. Preserve provider-local model tests and cross-repository API integration tests.

## Provider-side development utilities

GLTG's existing package, engine adapters, serializers and CLI remain available for development within this repository. The CLI commands `gltg evaluate` and `gltg reforecast` operate on provider-side JSON fixtures. A successful CLI run verifies that local utility, not Aivan's API integration. No utility must be removed merely because the product boundary is API-based.
