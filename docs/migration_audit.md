# GLTG Migration Audit

This document records the audit performed while migrating all GLTG logic into
the standalone `GiraffeTechnology/GLTG` repository and refactoring the consumer
repositories (`giraffe-agent`, `abcdYi`, `aivan`) to call GLTG only through its
HTTP API.

## Summary

Three distinct GLTG-related implementations existed across the consumer repos:

| Source | Location | Shape | Disposition |
|--------|----------|-------|-------------|
| **giraffe-agent** | `GLTG/` (full package, v1.0.0) | Rich evidence-weighted graph engine: models, estimation, graph, enumeration, reforecast, apparel templates, examples, 141 tests, docs, scripts | **Selected as source of truth.** Migrated wholesale into standalone `GLTG/`. |
| **abcdYi** | `libs/GLTG/gltg/` | Simplified `ParticipantNode`-based engine (engine.py 364 LOC, models.py 122 LOC) | **Obsolete duplicate.** Deleted from abcdYi; superseded by standalone GLTG + API client. |
| **aivan** | `src/aivan/leadtime/` + `GLTGClient` facade | Local apparel lead-time calculator (P50/P80/P90) with a **silent timeout fallback** | **Deleted.** Local calculation + silent fallback violate the "no local fallback / no silent substitution" rule. Replaced with thin HTTP client. |

### Conflict resolution

The giraffe-agent `GLTG/` package and the abcdYi `libs/GLTG/gltg` package
**conflict**: they expose different model shapes for the same concepts
(`ApparelOrderInput.participants`/`supplier_responses` vs.
`ApparelOrderInput.participant_nodes`). Per the migration rules these were not
silently merged.

**Decision:** the giraffe-agent package was selected because it is:

- the most complete and latest working implementation (v1.0.0, 141 passing tests);
- production-usable and deterministic (verified by `verify_gltg_5x.py`);
- already structured exactly like the target standalone layout (models/, services
  equivalents, enumeration/, graph/, reforecast/, apparel/, examples/, docs/);
- free of hidden LLM guessing;
- already graceful for 0/1/2/3+ suppliers (`run_zero_one_two_supplier_cases.py`).

The abcdYi `libs/GLTG` simplified engine and aivan's local calculator were
documented here and removed rather than migrated. Their useful *consumer-side*
mapping logic (DB order -> GLTG input) was preserved by rewriting it to build the
**API request DTO** instead of in-process engine objects.

## What the standalone repo gained

On top of the migrated giraffe-agent package, the standalone repo adds the
API-first contract required by all consumers:

- `src/gltg/api/` -- FastAPI app (`main.py`, `routes.py`, `schemas.py`).
- `src/gltg/services/` -- deterministic, API-facing lead-time / path / reforecast
  services that power the endpoints and handle 0/1/2/3+ suppliers without crashing.
- `Dockerfile`, `docker-compose.yml`, updated `.env.example`.
- `tests/api/` -- endpoint + edge-case tests.
- `scripts/run_api_edge_cases.py` -- in-process API edge-case verification.

The rich evidence-weighted engine (`gltg.engine.LeadTimeGraphEngine`) remains the
deep apparel source of truth and is still fully tested; the deterministic service
layer is the stable transport contract consumers integrate against.

## Per-file audit

### giraffe-agent (source of truth -> migrated, then removed locally)

| File / dir | Type | Disposition |
|------------|------|-------------|
| `GLTG/src/gltg/**` | core engine, models, estimation, graph, enumeration, reforecast, apparel | Migrated to standalone `src/gltg/**`; deleted from giraffe-agent |
| `GLTG/tests/**`, `GLTG/examples/**`, `GLTG/scripts/**`, `GLTG/docs/**` | tests/examples/scripts/docs | Migrated to standalone; deleted from giraffe-agent |
| `src/gltg/engine.py`, `src/gltg/__init__.py` | thin local re-export/adapter | Deleted; replaced by API client |
| `src/lead_time/**` (`path_enumerator.py`, `lead_time_calculator.py`, `path_ranker.py`, `models.py`) | embedded lead-time/path engine | Deleted; logic owned by standalone GLTG |
| `src/b_side/feasibility_engine.py`, `src/m_side/rollup/supplier_response_rollup.py`, `src/core_schema/b_side_types.py` | business-layer callers | Refactored to call GLTG API client (kept) |
| `src/integrations/gltg_client.py` | NEW thin HTTP client | Added |

### abcdYi

| File / dir | Type | Disposition |
|------------|------|-------------|
| `libs/GLTG/gltg/**` | duplicate engine | Deleted |
| `src/lead_time/gltg_adapter.py` | engine adapter | Rewritten to build API DTO + call client |
| `src/lead_time/calculator.py` | local path lead-time calc | Deleted/neutralized; GLTG owns it |
| `src/services/delivery_feasibility_service.py` | business service | Refactored to call API client |
| `src/decision_packets/service.py` | business service | Refactored to call API client (paths/enumerate) |
| `src/gpm/clients/giraffe_db_client.py` | DB client | Reviewed; GLTG references removed/redirected |
| `tests/unit/test_gltg_adapter.py`, `test_delivery_feasibility_service.py`, `test_decision_packet_uses_gltg.py` | tests of embedded engine | Rewritten to mock the GLTG API client |
| `src/integrations/gltg_client.py` | NEW thin HTTP client | Added |

### aivan

| File / dir | Type | Disposition |
|------------|------|-------------|
| `src/aivan/leadtime/**` (`calculator.py`, `explainer.py`, `models.py`) | local lead-time engine | Deleted |
| `src/aivan/integrations/gltg.py` | facade calling local calc + silent fallback | Rewritten as thin HTTP client (`GLTGClient`) |
| `src/aivan/execution/rfq_execution.py` | RFQ flow | Refactored to call GLTG via client (no local calc, no silent fallback) |
| `src/aivan/schemas/rfq.py` | `GLTGSimulation` DTO | Kept; populated from API response mapping |
| `scripts/run_aivan_private_domain_rfq_e2e.py` | E2E script | Updated to use live GLTG API |
| `tests/test_rfq_execution_iteration.py` | tests | Updated to mock the GLTG API client |

## Cleanup verification

After refactor, each consumer repo is checked so no embedded GLTG engine
imports/folders remain (only the thin HTTP client, docs, env vars, and tests
that mock the API). See each consumer PR's "cleanup verification" section and
`MIGRATION_TEST_REPORT.md`.
