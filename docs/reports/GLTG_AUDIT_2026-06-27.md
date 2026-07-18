# GLTG Full Audit — standalone service

**Repository:** GiraffeTechnology/gltg
**Audit date:** 2026-06-27
**Commit audited:** `dc9cda9` (branch `claude/new-session-3rkuj5`, even with `origin/main`)
**Scope:** `src/gltg/**` (engine, graph, enumeration, estimation, reforecast, packets, apparel, services, api, integrations), `tests/**`, `.github/workflows/ci.yml`
**Method:** full source read + empirical probes (160-test suite, determinism/edge scripts, in-process API client). All findings cite source `file:line`.

---

## Step 1 — Repository inventory

Standalone Python service, `gltg` v1.0.0, Python ≥3.11, deps `pydantic>=2` (+ `fastapi`/`uvicorn` optional). ~4,600 LOC of `src`.

There are **two independent computation layers** in the repo:

| Layer | Entry point | Lead-time model | Reached by |
|---|---|---|---|
| **Graph engine** | `engine.py::LeadTimeGraphEngine.evaluate` | Dependency graph + topological resolve + p50/p80/p90 + evidence weighting | Python API (`gltg` import), CLI, tests/scripts |
| **Deterministic service** | `services/lead_time_service.py::estimate` (+ `path_enumeration_service`, `reforecast_service`) | Per-supplier **sum** of `material+production+qc+logistics`, capacity-floored | The **HTTP API** (`/v1/*`) |

This split is the central finding (DEFECT-01).

Build state: `pytest` → **160 passed**; `verify_gltg_5x.py`, `run_api_edge_cases.py`, `run_zero_one_two_supplier_cases.py` → **PASS**. `docs/` (10 files) and `.env.example` referenced by the README all exist.

---

## Step 2 — API surface (HTTP)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/health` | `api/routes.py:24` | `{"status":"ok","service":"gltg"}` |
| GET | `/version` | `api/routes.py:29` | `{"service":"gltg","version":"1.0.0","api_version":"v1"}` |
| POST | `/v1/lead-time/estimate` | `api/routes.py:38` → `services.estimate` | summed-stage model |
| POST | `/v1/paths/enumerate` | `api/routes.py:47` → `services.enumerate_paths` | SINGLE_SOURCE + PARALLEL_SPLIT |
| POST | `/v1/reforecast` | `api/routes.py:56` → `services.reforecast` | additive per-stage deltas |

**None of the five routes touch `LeadTimeGraphEngine`** (`grep` over `api/`, `services/` returns no engine reference; `engine.py:103 evaluate` has no HTTP caller). `/version` and `/health` exist and are correct (this was a gap in the abcdYi embed; fixed here).

---

## Step 3 — Core logic audit

Rules mapped onto both layers. "Engine" = `LeadTimeGraphEngine`; "Service" = HTTP layer.

| Rule | Verdict | Evidence |
|---|---|---|
| LT-01 Parallel stage isolation | **PASS (engine) / PARTIAL (service)** | Engine: fabric/trim/packaging are separate graph branches merging at CUTTING/SEWING via `builder.py:16` edge rules + `dependency_resolver.py:179` `max(predecessor finish)`. Service: no parallelism, no trims — `lead_time_service.py:81` sums `material+prod+qc+logistics`. |
| LT-02 Sequential chaining | **PASS** | Engine topological forward pass; Service sum. |
| LT-03 Total lead-time formula | **PASS** | Engine = longest commitable chain; Service = staged sum. |
| LT-04 Multiple output dates | **PASS** | Engine packet exposes earliest/most_likely/commitable/risk_adjusted (`packet.py`); Service exposes p50/p80/p90/minimum + earliest (`lead_time_service.py:227`). |
| LT-05 Risk-buffer source | **PASS** | Engine derives `risk_adjusted = commitable_start + max(max_days, ceil(p90*1.15))` from per-node estimates (`dependency_resolver.py:200`) — not a hardcoded global. Service bands scale with confidence (`lead_time_service.py:107`). (Improvement over abcdYi DEFECT-03.) |
| LT-06 Ranked options ≤3 + ranking | **PARTIAL** | Cap correct (`engine.py:132,165`; `option_ranker.py:601`). But options are **not differentiated by factory** — DEFECT-02. |
| LT-07 Zero/one/two-supplier edge cases | **PASS** | Service: structured `NO_SUPPLIERS`/`LIMITED_COMPARISON`/`LIMITED_SUPPLIER_POOL` (`lead_time_service.py:171-212`); Engine: `feasibility_packet.py:913-947` NO_FEASIBLE_OPTION/LIMITED_OPTIONS. e2e green. Strong. |
| LT-08 Reforecast from current state | **PARTIAL** | Service reforecast is deterministic (additive deltas on copies, `reforecast_service.py:24`). Engine reforecast uses `date.today()` as re-resolve start — DEFECT-04. |
| LT-09 Input validation (422 not 500) | **PARTIAL** | HTTP 422 verified for missing/negative/out-of-range/malformed bodies; 404 for unknown route. No global exception handler / unified error body — DEFECT-05. |
| LT-10 `deadline_days` → target conversion | **PASS** | `_effective_target` honors `deadline_days` (`lead_time_service.py:62`); CI asserts `estimated_lead_time_days:28` for a `deadline_days:60` request. (Improvement over abcdYi LT-10 N/A.) |
| ARCH-01 Single implementation / source of truth | **FAIL** | Two divergent lead-time engines in one repo — DEFECT-01. |

---

## Step 4 — Test coverage

25 test modules, 160 tests, all green. Strong coverage of: zero/one/two/3+ suppliers (unit + e2e + api), determinism ×5, batch-split, evidence weighting, critical path, duration estimator, risk flags, giraffe-agent adapter, percentile bands.

| Scenario | Covered? | Location |
|---|---|---|
| 0/1/2/3+ suppliers never crash (HTTP + engine) | YES | `tests/e2e/*`, `tests/api/test_api_endpoints.py` |
| Determinism (5×) | YES | `tests/e2e/test_reproducibility_5x.py` |
| `deadline_days` honored | YES | CI + `tests/api/test_percentiles_and_baselines.py` |
| 422 on malformed input | YES (implicit via FastAPI) | — |
| **HTTP API uses the graph engine** | **NO** | no test asserts engine ↔ HTTP parity — DEFECT-01 |
| **Distinct factories → distinct dates** | **NO** | `tests/unit/test_path_enumerator.py` asserts counts/presence only, never that a slower factory yields a later date — DEFECT-02 |
| **Engine reforecast determinism** | **NO** | `tests/integration/test_reforecast.py` does not pin wall-clock — DEFECT-04 |
| capacity_per_day affects engine duration | NO | DEFECT-03 |

---

## Step 5 — CI audit

`.github/workflows/ci.yml`: Python 3.11, installs `-e .[dev]`, runs `pytest -q`, the three verification scripts, then boots uvicorn and curls all 5 endpoints (asserting `estimated_lead_time_days:28`, `paths`, `updated_lead_time_days`). Solid end-to-end gate. Gaps: single Python version (3.11 only; `pyproject` allows ≥3.11 incl. 3.12/3.13 where `datetime.utcnow()` warns — DEFECT-06); no lint/type/format stage; CI exercises only the HTTP layer, so the graph engine's option/reforecast correctness is never gated by the HTTP smoke tests (only by `pytest`).

---

## Step 6 — Defect report

### DEFECT-01 — HTTP API never uses the graph engine; two divergent lead-time implementations
**Severity:** HIGH (architectural) · **Rule:** ARCH-01 / LT-01 · **Status:** OPEN
The README's premise is "exactly one implementation of lead-time / path / reforecast logic," consumed over HTTP. But the HTTP routes call `services.*` (`api/routes.py:38,47,56`), which implement a **simple summed-stage** calculator (`lead_time_service.py:81`), while the sophisticated `LeadTimeGraphEngine` (graph, evidence weighting, critical path) is reachable only via in-process Python import/CLI/tests. For the same order the two layers return different numbers, and every HTTP consumer (`giraffe-agent`/`abcdYi`/`aivan`) gets the simple model — i.e. precisely the `max(...)+production+QC+shipping` calculator the README says GLTG "is not." The repo therefore re-creates, inside itself, the divergence it was created to eliminate.
**Recommended fix:** Decide the contract. Either (a) wire the HTTP service layer onto `LeadTimeGraphEngine` (map `SupplierInput` → `ApparelOrderInput`, return engine packets) so HTTP and Python agree, or (b) explicitly demote the engine to "advanced/offline" and document that `/v1/*` is the supported summed-stage contract. Add a parity test asserting HTTP and engine agree (or are documented to differ) for a reference order.

### DEFECT-02 — Multi-factory path options are not differentiated (all share the first factory's schedule)
**Severity:** HIGH · **Rule:** LT-06 · **Status:** OPEN
`GraphBuilder` assigns the **first** participant that `can_handle` each node type (`order_mapper.py:91`), resolves dates once, and `PathEnumerator._create_option` reuses the same `terminal_node` dates and `graph.nodes` for every factory option (`path_enumerator.py:519-553`). Only `participant_combination` differs.
**Proof:** with two garment factories (5000/day vs 200/day) for a 10,000-unit order, both options return identical `commitable=2026-12-18`, `most_likely=2026-10-25`, independent of ordering:
```
[FAST,SLOW]  FAST 2026-12-18 / SLOW 2026-12-18
[SLOW,FAST]  SLOW 2026-12-18 / FAST 2026-12-18
```
The ranker's FASTEST/MOST_RELIABLE labels are then assigned among identical-dated options, so "ranked alternatives across participant combinations" is cosmetic.
**Recommended fix:** Re-resolve a graph per factory combination (assign that factory to factory-owned nodes, re-estimate durations, re-run `DependencyResolver`) before building each option, then enumerate/rank on the per-combination dates.

### DEFECT-03 — Engine ignores `capacity_per_day` for production duration
**Severity:** HIGH (root cause of DEFECT-02 for production) · **Rule:** LT-03 · **Status:** OPEN
`capacity_per_day` is on `ParticipantProfile`/`Capability` and parsed by the adapter (`giraffe_agent_adapter.py:72,95`) but **never consumed** in the engine (`grep` shows zero use outside `services/`/`api/`). Engine SEWING duration comes from quantity-scaled baseline (`apparel/baselines.py:_sewing_baseline`) blended with `typical_lead_days` — a 200/day and a 5000/day factory get the same sewing duration. Only the HTTP `lead_time_service._capacity_adjusted_production_days` honors capacity.
**Recommended fix:** Feed `capacity_per_day` into the engine's production-node estimate (capacity floor = `ceil(quantity / effective_capacity)`), mirroring the service-layer logic, so the graph respects stated throughput.

### DEFECT-04 — Engine reforecast is non-deterministic (`date.today()` re-resolve anchor)
**Severity:** MEDIUM · **Rule:** LT-08 · **Status:** OPEN
`ReforecastEngine.reforecast` sets `start = date.today()` for the re-resolve (`reforecast_engine.py:572`), so engine reforecast output depends on the wall-clock day it runs and ignores the order's `evaluation_date`. Determinism is a stated GLTG guarantee (and is enforced for the forward pass and the HTTP layer).
**Recommended fix:** Thread the original `evaluation_date` (or the packet's `generated_at` date) through `reforecast()` instead of `date.today()`; cover with a test that pins two different "today" values and asserts identical output.

### DEFECT-05 — No global exception handler / unified HTTP error contract
**Severity:** MEDIUM · **Rule:** LT-09 · **Status:** OPEN
`api/main.py` registers no exception handler. FastAPI/Pydantic give clean 422s, and the deterministic service layer is written not to raise, so today no 500 path is reachable via HTTP — but any future unexpected error (or wiring the engine per DEFECT-01, which can raise `CyclicDependencyError`/`GraphResolutionError`) would surface as an unstructured 500 with no `{"error","code"}` body. The `gltg.errors` hierarchy exists but is unmapped to HTTP.
**Recommended fix:** Add an exception handler mapping `GLTGError` subclasses to structured 4xx/5xx bodies (`{"error","code"}`), and a catch-all 500 with a stable shape.

### DEFECT-06 — `datetime.utcnow()` (naive, deprecated) in 9 sites
**Severity:** LOW · **Status:** OPEN
9 calls across `duration_estimator.py`, `order_mapper.py`, `feasibility_packet.py`, `reforecast_engine.py`. Naive UTC timestamps; deprecated on Python 3.12+ (which `pyproject`'s `>=3.11` permits). Packets' `generated_at` is tz-naive.
**Recommended fix:** `datetime.now(timezone.utc)` throughout; consider serializing tz-aware.

### DEFECT-07 — `CalendarCalculator.next_working_day` is dead/buggy
**Severity:** LOW · **Status:** OPEN
`calendars.py:52-58`: returns `add_working_days(d, 0, config)` which (days=0) returns `d` unchanged — it does **not** advance to the next working day — and lines 57-58 are unreachable code after `return`. The working implementation is `ensure_working_day`; `next_working_day` appears unused but is a latent trap.
**Recommended fix:** Delete `next_working_day` (or redirect it to `ensure_working_day`).

### DEFECT-08 — Critical path is a "latest-finish chain" heuristic, not slack-based CPM
**Severity:** LOW · **Rule:** LT-06 · **Status:** OPEN
`CriticalPathFinder.find` (`critical_path.py:228`) back-traces the predecessor with the latest `commitable_finish` and ignores edge `lag_days` in the trace. This yields a plausible bottleneck chain but is not a true zero-slack critical path; with start-to-start/lag edges it can mis-attribute the critical node.
**Recommended fix:** If CPM rigor is required, compute late-start/late-finish and select zero-slack nodes; otherwise rename to "longest-finish path" in docs to set expectations.

---

## Step 7 — Integration readiness

- **Versioning:** `/version` + `/health` present and correct; `__version__` single-sourced (`version.py`). Good.
- **Error contract:** 422 (validation), 404 (route), 200-with-structured-`warnings` (edge cases) verified. No unified error body for unexpected failures (DEFECT-05).
- **Determinism:** HTTP layer deterministic (anchored on `evaluation_date`/`date.today()` only when no anchor given); engine forward pass deterministic; **engine reforecast is not** (DEFECT-04).
- **Caller assumptions:** dates are ISO `YYYY-MM-DD`; lead-time units are calendar days unless a `CalendarConfig` is supplied; HTTP `estimated_lead_time_days` is a staged **sum** (not graph-derived) — consumers must not assume it equals the engine packet's commitable math (DEFECT-01).
- **Breaking-change risk:** if DEFECT-01 is fixed by wiring HTTP→engine, `estimated_lead_time_days` and option dates will move materially for every consumer; stage as a versioned change (`/v2` or explicit migration).

---

## Step 8 — Summary

### Scorecard

| Check | Status | Defects |
|---|---|---|
| LT-01 Parallel isolation | PASS (engine) / PARTIAL (service) | DEFECT-01 |
| LT-02 Sequential chaining | PASS | — |
| LT-03 Total formula | PASS | DEFECT-03 (capacity ignored in engine) |
| LT-04 Output dates | PASS | — |
| LT-05 Risk buffer | PASS | — |
| LT-06 Ranked options | PARTIAL | DEFECT-02, DEFECT-08 |
| LT-07 Edge cases | PASS | — |
| LT-08 Reforecast | PARTIAL | DEFECT-04 |
| LT-09 Input validation | PARTIAL | DEFECT-05 |
| LT-10 `deadline_days` | PASS | — |
| ARCH-01 Single implementation | FAIL | DEFECT-01 |

**Core rules: 6 PASS / 1 FAIL / 4 PARTIAL.** **Defects: 3 HIGH · 2 MEDIUM · 3 LOW.**

Overall: materially stronger than the abcdYi embed — real graph model, p50/p80/p90, evidence weighting, `/version`+`/health`, `deadline_days` honored, configurable risk buffers, robust 0/1/2/3+ edge handling, 160 green tests, full CI smoke. The dominant risk is **architectural**: the HTTP contract that consumers actually use bypasses the engine, and the engine's multi-option/reforecast paths have correctness gaps (factory undifferentiation, capacity ignored, non-deterministic reforecast).

### Recommended fix order

**P0** — DEFECT-01 (decide & wire/document the HTTP↔engine contract; add parity test). Resolving this scopes the rest.
**P1** — DEFECT-02 + DEFECT-03 (per-factory re-resolve incl. capacity) — only fully testable once P0 picks the engine path; DEFECT-04 (deterministic reforecast).
**P2** — DEFECT-05 (error handler), DEFECT-06 (`utcnow`), DEFECT-07 (dead method), DEFECT-08 (CPM rigor or rename); CI: add 3.12/3.13 matrix + lint/type stage.

*Audit complete. Findings from source read + empirical probes on commit `dc9cda9`. No production data accessed.*
