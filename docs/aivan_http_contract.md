# Aivan HTTP Contract Checkpoint

This document describes the HTTP surface implemented by this candidate. It is
not evidence of production deployment or complete Aivan integration.

## Runtime entrypoint

Run GLTG from the repository root with the package source on `PYTHONPATH`:

```text
python -m uvicorn gltg.api.main:app --host 127.0.0.1 --port 8090
```

Set `GLTG_INBOUND_SERVICE_AUTH_SECRET` through the deployment secret manager.
Do not put the value in commands, logs, fixtures, or repository files.

## Trusted Aivan headers

The Aivan discovery and v2 evaluation calls send these headers:

```text
X-Service-Auth
X-Service-Tenant-ID
X-Service-ID
X-GLTG-Contract-Version
X-AIVAN-Correlation-ID
X-Service-Capability
```

Discovery is `GET /api/gltg/v1/discovery`. The accepted contract is
`gltg.lead-time.v1`, the capability is `lead-time.evaluate`, and the evaluation
path is `POST /v2/lead-time/simulate`.

## Direct v2 calculation

A direct v2 request contains a tenant-bound request and trace identity, a real
supplier identifier, observed order and supplier facts, and evidence record
identifiers. The deterministic response preserves:

- the supplier identifier under `assessment_packet.case_context.supplier_id`;
- canonical `quantiles.p50_days`, `p80_days`, and `p90_days`;
- the calculation breakdown under `components` and `explanation_json`;
- evidence identifiers under `source_observation_ids` and packet evidence refs;
- an explicit persistence status.

The loopback HTTP check for this candidate used synthetic identifiers and facts,
executed the real ASGI application through Uvicorn, and returned HTTP 200 with
P50/P80/P90 `22.0/25.96/29.7`. It did not use a prebuilt response.

## Private snapshot request

Current Aivan orchestration sends:

```json
{"private_snapshot_reference":{"snapshot_id":"...","tenant_id":"...","contract_version":"snapshot.v1"}}
```

GLTG accepts and tenant-checks the complete immutable reference envelope. The
selected giraffe-db Data API does not expose a snapshot read operation, so GLTG
cannot retrieve the normalized payload. A matching reference therefore returns
HTTP 503 with `PRIVATE_SNAPSHOT_RESOLUTION_UNAVAILABLE`; a tenant mismatch
returns HTTP 403 before any resolution attempt.

This fail-closed result is the current integration truth. Complete G03 requires
a versioned, tenant-authenticated Data API read operation plus real HTTP tests
for facts, evidence, GLTG result persistence, receipt readback, restart, and
recovery. GLTG must not accept private facts from the consumer as a workaround.

## Legacy Aivan calls

The older Aivan facade still calls `/v1/lead-time/estimate` with supplier ID
`requirement` and no trusted identity headers, or calls the direct v2 DTO without
the required headers. The v1 response can preserve its supplied identifier and
stage trace, but it does not prove tenant-bound facts, evidence lineage, or
persistence. The headerless v2 form correctly fails closed. Neither legacy path
is counted as G03 completion for the current authenticated orchestration.
