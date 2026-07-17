# Stage 3 — Final Validation Report

Date: 2026-07-17. All results produced on the final Stage 3 tree (Python
3.11.15). Companion documents: `STAGE3_GLTG_LOGIC_AUDIT.md`,
`STAGE3_API_EXECUTABILITY_AUDIT.md`, `STAGE3_GIRAFFE_DB_INTEGRATION_AUDIT.md`,
`STAGE3_README_CLAIM_MATRIX.md`, `STAGE3_REDUNDANCY_REPORT.md`,
`gltg_rule_inventory.json`.

## The ten required answers

| Question | Answer |
| --- | --- |
| Is v1 executable? | **Yes.** Real graph-engine computation behind all three v1 routes, live-executed in tests, scripts, and CI curls. |
| Is v2 executable? | **Yes.** The deterministic rule engine is now the **default** v2 path (`evaluation_mode="deterministic"`). Pre-Stage-3 the default silently attempted an external LLM and degraded to manual-review stubs; that path is now strictly explicit opt-in (`GLTG_EVALUATOR_MODE=llm`) and classified *experimental*. |
| Is GLTG deterministic? | **Yes** in default mode: no RNG, run id = SHA-1 of the canonical request; repeated identical calls return identical bodies (tested at simulator, app-object, and live-HTTP levels). LLM mode is inherently not guaranteed deterministic and is opt-in + labeled. v1 note: without an explicit `order_date`/`evaluation_date` the anchor is `date.today()` (deterministic within a day; disclosed). |
| Can it consume real giraffe-db evidence? | **Yes.** New authenticated client + per-request opt-in (`evidence.use_giraffe_db`). Proven over real HTTP against a live giraffe-db (below). |
| Can it persist runs? | **Yes** (opt-in `GLTG_PERSIST_RUNS=true`): POSTs to `/api/data/gltg-simulation-runs`; `persistence.status ∈ {persisted, skipped, failed, unavailable}` is truthful and tested for all four outcomes. Persisted run verified by direct row inspection of the fresh DB in the E2E. |
| Are P50/P80/P90 real calculations? | **Yes** in deterministic mode: baseline + behavioral central shift + uncertainty inflation through three explicit composers with monotonic repair. Constants are versioned (`rule_version`) but uncalibrated (`calibration_version="none"`) — accuracy is **not** claimed (synthetic data only). |
| Are behavior adjustments real? | **Yes.** Tiered deterministic rules; every nonzero adjustment appears in `explanation_json.adjustments` (tested). |
| Does reforecast use new evidence? | **Yes (fixed in Stage 3).** Pre-Stage-3, `/v2/reforecast` ignored events entirely. It now applies typed events, recomputes, and discloses `previous_quantiles`, per-quantile `delta`, `changed_components`, `triggering_observation_ids`; unknown events are listed in `unapplied_events` with a warning. |
| Does tenant isolation hold? | **Yes**, end to end: `tenant_id` propagates as `X-Service-Tenant-ID`; wrong tenant cannot read evidence (giraffe-db returns 404 → explicit `EVIDENCE_NOT_FOUND`, manual review); missing/wrong service auth fails closed (401/403 at giraffe-db; GLTG surfaces 502 `EVIDENCE_AUTH_FAILED`). |
| What remains non-production-ready? | See "Production-readiness gaps" below. |

## Real HTTP end-to-end (GLTG ↔ giraffe-db) — 17/17 PASS

`scripts/validate_gltg_giraffe_db_e2e.py`: fresh giraffe-db SQLite DB →
`alembic upgrade head` → synthetic supplier import (1,500 rows) → live
giraffe-db uvicorn (auth enforced) → live GLTG uvicorn → real HTTP.
No fixtures, no monkey-patched clients, no mocked HTTP.

```text
[PASS] both services live over real HTTP
[PASS] GLTG /ready reports giraffe-db ok without secrets
[PASS] giraffe-db missing auth fails closed (401)
[PASS] giraffe-db wrong tenant cannot read supplier (404)
[PASS] GLTG v2 simulate with evidence is 200
[PASS] quantiles are real and monotonic — {"p50_days": 44.0, "p80_days": 51.92, "p90_days": 59.4}
[PASS] supplier record + behavior summary retrieved from giraffe-db
       (GDB_SYN_V1_SUP_000001, tenant-demo, retrieved=[supplier_record, behavior_summary])
[PASS] synthetic evidence disclosed (SYNTHETIC_EVIDENCE)
[PASS] missing behavior evidence disclosed (no invention)
[PASS] deterministic evaluation mode
[PASS] run persisted to giraffe-db and verified in the fresh DB
       (GDB_SYN_V1_GLTG_000001; row matches tenant, supplier, P50)
[PASS] repeated call: identical run id, quantiles and risk
[PASS] wrong tenant cannot read evidence via GLTG (explicit EVIDENCE_NOT_FOUND)
[PASS] wrong GLTG service secret fails closed (502 EVIDENCE_AUTH_FAILED)
[PASS] impossible deadline: infeasible + high risk + manual review
[PASS] reforecast applies events and discloses previous vs new quantiles
[PASS] giraffe-db down: explicit 503 DB_UNAVAILABLE (no silent fallback)
{"checks": 17, "failed": 0}
```

giraffe-db side note: run reads have no dedicated
`GET /api/data/gltg-simulation-runs/{id}` route (documented gap in
`STAGE3_GIRAFFE_DB_INTEGRATION_AUDIT.md`); verification used the create
response plus direct DB row inspection.

## Acceptance scenarios (§16)

| # | Scenario | Result |
| --- | --- | --- |
| 1 | 10,000 shirts, 3+ suppliers | `scripts/run_10000_shirts_acceptance.py` → PASS |
| 2 | No suppliers | infeasible + `NO_SUPPLIERS`, no crash (script + tests) |
| 3 | One supplier | `LIMITED_COMPARISON` warning (tests + script) |
| 4 | Supplier response delay | visible effect: reforecast delta ≥ 0 with explanation (`tests/stage3/test_reforecast_v2.py`) |
| 5 | Missing behavior evidence | `MISSING_BEHAVIOR_EVIDENCE` warning + confidence reduced, quantiles unchanged (no invention) — tested and proven live in E2E |
| 6 | Impossible deadline | infeasible + `deadline_risk_level=high` + manual review (live E2E) |
| 7 | Reforecast after capacity/logistics change | applied events, previous-vs-new quantiles, changed components (live E2E) |
| 8 | Wrong tenant | evidence access denied; explicit warning + manual review (live E2E) |

## Test evidence

- Full suite, five consecutive runs on the final tree (`python -m pytest -q`):
  `307 passed` every run (3.7–4.1s). Baseline before Stage 3: 241 passed.
- `python -m compileall -q src tests scripts` clean; ID-contract scan PASS.
- Determinism script `verify_gltg_5x.py` PASS; edge cases and 0/1/2 supplier
  scripts PASS.
- Docker: the Dockerfile now declares non-root execution (`USER gltg`,
  uid 10001). The validation environment has no Docker daemon, so the local
  build could **not** be executed here; the new CI job performs the real
  build + startup smoke (`/health`, `/ready`, deterministic v2 call,
  non-root uid assertion) on every push.
- CI additions: shipped-default v2 contract curls, reforecast delta check,
  `/ready`, Docker job, and a real-HTTP giraffe-db E2E job that runs when a
  `GIRAFFE_DB_CI_TOKEN` secret is configured (giraffe-db is private; without
  the token the job reports the skip explicitly instead of faking success).

## Production-readiness gaps (honest list)

1. **No calibration**: quantile constants and behavior tiers are versioned
   but never fitted to real outcome data (`calibration_version="none"`).
   Accuracy claims are prohibited until real transaction evidence exists.
2. **No inbound auth on GLTG itself**: GLTG trusts its callers (internal
   service posture). Outbound giraffe-db auth is enforced; inbound
   authn/z must come from the platform layer.
3. **Baseline retrieval is caller-driven**: category/route/pair statistical
   baselines are not yet fetched from giraffe-db (only supplier record +
   behavior summary are).
4. **giraffe-db run read-back route missing** (gap documented; persistence
   verified via create response + DB row).
5. **Dependency pinning**: floor pins + `uv.lock`, but CI installs with pip
   (unlocked). Acceptable for a library-style service; noted.
6. **Structured logging / correlation IDs**: not implemented; uvicorn
   defaults only.
7. **CI real-HTTP E2E is token-gated** because giraffe-db is private; the
   acceptance run recorded here was executed against a live giraffe-db
   (Stage 2A tree) locally. The E2E also depends on giraffe-db Stage 2A
   (bridge importer + supplier profile) being merged.
8. **LLM mode** remains experimental: non-deterministic by nature, external
   dependency, and must never be enabled where the canonical boundary
   forbids LLM calculations.
