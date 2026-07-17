# Stage 3 — API Executability Audit (read-only, pre-change)

Date: 2026-07-17. Method: code inspection plus live execution of the actual
app object and live HTTP (`uvicorn`) — route existence was **not** treated
as proof.

## v1 API — EXECUTABLE (real)

| Route | Status | Evidence |
| --- | --- | --- |
| `GET /health` | executes | returns `{"status":"ok","service":"gltg"}`; process-alive only |
| `GET /version` | executes | returns package version + `api_version: v1` |
| `POST /v1/lead-time/estimate` | executes, real calculation | routes through `engine_adapter.estimate` → `LeadTimeGraphEngine.evaluate` (graph critical path); CI curl asserts the engine value (124d for the 10k-shirt case) |
| `POST /v1/paths/enumerate` | executes, real calculation | per-supplier single-source paths + parallel-split synthesis, deterministic ranking |
| `POST /v1/reforecast` | executes, real calculation | baseline estimate → `_apply_events` (per-supplier stage deltas) → re-estimate → delta disclosed |

Edge behavior verified (tests + scripts + live calls): 0 suppliers →
`NO_SUPPLIERS`, infeasible, no crash; 1 supplier → `LIMITED_COMPARISON`
(estimate) / `SINGLE_SOURCE_RISK` (paths); 2 suppliers →
`LIMITED_SUPPLIER_POOL`; 3+ → normal comparison. Malformed input → 422 with
the unified `{"error", "code":"VALIDATION_ERROR"}` envelope; domain errors →
422 `{"error", code}`; unexpected → structured 500. Repeated identical calls
return identical bodies (no RNG, no clock dependence when
`evaluation_date`/`order_date` is supplied; **note**: when no anchor date is
given, v1 anchors to `date.today()` — deterministic within a day, disclosed
here).

## v2 API — routes execute, but the default path is not a calculation

| Route | Status (pre-Stage-3) |
| --- | --- |
| `POST /v2/lead-time/simulate` | Executes. Default config (`GLTG_EVALUATOR_MODE=llm`, provider `qwen`) attempts an external DashScope call; with no key/network the response is a manual-review stub (P50=1.0/P80=5.0/P90=8.0 placeholders, `EVALUATOR_UNAVAILABLE`) still labeled `evaluation_mode="llm"`. With `GLTG_EVALUATOR_MODE=fallback` it runs the real deterministic simulator. With provider `mock` (CI) it exercises the packet-validation path with fixture-derived packets — MOCK_ONLY as calculation proof |
| `POST /v2/paths/enumerate` | Executes: runs one simulation per entry, ranks by selected-confidence days deterministically. Inherits the v2 default-path problem |
| `POST /v2/reforecast` | Executes but **does not apply events** (echoes them); no previous/new/delta disclosure — PARTIALLY_IMPLEMENTED |

Required v2 response contract check (pre-Stage-3):

| Field | Present? |
| --- | --- |
| `gltg_run_id`, `model_version`, `rule_version`, `calibration_version` | yes (run id = input hash, deterministic) |
| `quantiles.p50/p80/p90_days` | yes, monotonic-repaired |
| `components` | yes (23 named day components) |
| `risk.deadline_risk_level/confidence_score/fallback_supplier_required/manual_review_required/deadline_feasible/selected_confidence_days` | yes |
| `explanation_json`, `warnings` | yes (stable warning codes) |
| `persistence` | partial — bare `persisted_to_giraffe_db: false` bool; no `persisted/skipped/failed/unavailable` status |
| `source_observation_ids` (top level) | **missing** (only inside `explanation_json`) |

## Reliability / security posture (pre-Stage-3)

- `/ready` endpoint: **absent** (only `/health`, which conflates liveness
  and readiness by implication).
- Docker: runs as **root**; base `python:3.11-slim`; honors
  `GLTG_HOST/GLTG_PORT`.
- Dependencies: floor-pinned only (`>=`); `uv.lock` exists but CI installs
  with pip (does not use the lock).
- Auth/tenant: the service itself has **no** inbound auth (documented as an
  internal service); `tenant_id` is accepted in v2 requests and echoed in
  packets but propagated nowhere (there is no downstream call).
- Timeouts/retries: provider calls have `timeout_seconds` (30) and
  `max_retries` (2); there is no other outbound dependency.
- Secrets: `GLTG_LLM_API_KEY` read from env, sent only as Authorization
  header; not logged (no logging of settings found).
- Logging: no structured logs or correlation IDs; FastAPI/uvicorn defaults.
- CI (pre-Stage-3): compileall, pytest (241), ID-contract scan, edge-case
  scripts, 5x determinism script, live uvicorn + curl checks of all three
  v1 endpoints on Python 3.11/3.12/3.13. v2 covered only via mock provider.
  No Docker build, no giraffe-db integration, no real-HTTP v2 acceptance.
