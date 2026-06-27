# GLTG Migration Test Report

Verification of the GLTG standalone migration and the **complete removal** of
embedded GLTG / lead-time engines from all three consumer repositories.

## Status: COMPLETE

- GLTG standalone service: engine + API + Docker + docs + tests.
- giraffe-agent, abcdYi, aivan: **no embedded GLTG engine code**; all call GLTG
  through `GLTG_API_BASE_URL` via a thin HTTP client; no silent local fallback.

## Environment

- Python 3.11
- GLTG installed with `pip install -e ".[dev]"`
- Live GLTG server: `uvicorn gltg.api.main:app --host 0.0.0.0 --port 8090`
- Consumers run against `GLTG_API_BASE_URL=http://localhost:8090`

## Exact commands

```bash
# GLTG
cd GLTG && python -m pip install -e ".[dev]"
python -m pytest -q                                   # 158 passed
python scripts/run_api_edge_cases.py                  # 0/1/2/3+ suppliers: PASS
python scripts/verify_gltg_5x.py                      # determinism: PASS
python scripts/run_zero_one_two_supplier_cases.py     # PASS
uvicorn gltg.api.main:app --host 0.0.0.0 --port 8090
curl http://localhost:8090/health   # {"status":"ok","service":"gltg"}
curl http://localhost:8090/version  # {"service":"gltg","version":"1.0.0","api_version":"v1"}

# giraffe-agent
cd giraffe-agent && python -m pytest -q                # 632 passed, 2 skipped
GLTG_API_BASE_URL=http://localhost:8090 RUN_GLTG_INTEGRATION_TESTS=1 \
  python -m pytest tests/test_gltg_client_integration.py -q   # 2 passed (live)

# abcdYi
cd abcdYi && DATABASE_URL="sqlite+aiosqlite:///./t.db" SECRET_KEY=test \
  python -m pytest tests/unit -q -m "not integration"  # 463 passed, 2 skipped
GLTG_API_BASE_URL=http://localhost:8090 RUN_GLTG_INTEGRATION_TESTS=1 \
  DATABASE_URL=... SECRET_KEY=test \
  python -m pytest tests/unit/test_gltg_client_integration.py -q  # 2 passed (live)

# aivan
cd aivan && python -m pytest -q                        # 401 passed, 2 skipped
GLTG_API_BASE_URL=http://localhost:8090 RUN_GLTG_INTEGRATION_TESTS=1 \
  python -m pytest tests/test_gltg_client_integration.py -q  # 2 passed (live)
```

## Full verification, 5 runs

Each run = GLTG unit + API tests, GLTG API edge cases (0/1/2/3+ suppliers),
5x determinism check, and engine zero/one/two supplier cases.

```
Run 1/5: PASS  (gltg: 158 passed | edge: PASS | 5x: PASS | 0/1/2: PASS)
Run 2/5: PASS  (gltg: 158 passed | edge: PASS | 5x: PASS | 0/1/2: PASS)
Run 3/5: PASS  (gltg: 158 passed | edge: PASS | 5x: PASS | 0/1/2: PASS)
Run 4/5: PASS  (gltg: 158 passed | edge: PASS | 5x: PASS | 0/1/2: PASS)
Run 5/5: PASS  (gltg: 158 passed | edge: PASS | 5x: PASS | 0/1/2: PASS)
```

**Run 1/5: PASS**
**Run 2/5: PASS**
**Run 3/5: PASS**
**Run 4/5: PASS**
**Run 5/5: PASS**

No failures across the five runs; determinism spread = 0 days.

## Supplier edge cases (API)

| Suppliers | feasible | estimated_lead_time_days | warnings | paths |
|-----------|----------|--------------------------|----------|-------|
| 0 | false | null | `NO_SUPPLIERS` | 0 |
| 1 | true | 28 | `LIMITED_COMPARISON` | 1 |
| 2 | true | 28 | `LIMITED_SUPPLIER_POOL` | 3 |
| 3+ | true | 28 | (none) | 5 |

No crash in any case.

## Consumer test suites (post-removal)

| Repo | Result |
|------|--------|
| giraffe-agent | 632 passed, 2 skipped (deleted 7 obsolete engine test files; added client + contract tests) |
| abcdYi | 463 passed, 2 skipped (unit/sqlite; deleted 3 obsolete engine test files; rewired gltg tests) |
| aivan | 401 passed, 2 skipped (deleted local-calculator test; replaced timeout-fallback test) |

## Live API integration calls (consumer -> GLTG)

Each consumer made real HTTP calls to the running GLTG server:

- giraffe-agent: `tests/test_gltg_client_integration.py` -> 2 passed
- abcdYi: `tests/unit/test_gltg_client_integration.py` -> 2 passed
- aivan: `tests/test_gltg_client_integration.py` -> 2 passed

## Residue checks (requirement 6/7)

Command:

```bash
rg -n "embedded GLTG|local implementation is the embedded GLTG engine|from src.gltg|import src.gltg|from gltg|import gltg|libs/GLTG|GLTG/src|calculate_gltg_lead_time_path|calculate_apparel_leadtime|LeadTimeGraphEngine|path_enumerator|reforecast_engine" .
```

Results in the three consumer repos (`src tests pyproject.toml`):

- **giraffe-agent**: only `tests/conftest.py: from src.integrations import gltg_client`
  (the permitted API-client import). No embedded engine, no `src/gltg`, no
  `calculate_gltg_lead_time_path`, no `path_enumerator`.
- **abcdYi**: only `tests/conftest.py: from src.integrations import gltg_client`.
  No `libs/GLTG`, no `gltg` pyproject dependency, no engine modules.
- **aivan**: only `tests/conftest.py: from aivan.integrations import gltg_client`.
  No `aivan.leadtime`, no `calculate_apparel_leadtime`, no local calculator used
  by `GLTGClient`.

The only remaining matches are the `gltg_client` API-client imports, which
requirement 7 explicitly allows ("GLTG references only as API client / docs /
env vars / mocked API tests"). The forbidden engine tokens
(`LeadTimeGraphEngine`, `path_enumerator`, `reforecast_engine`,
`calculate_gltg_lead_time_path`, `calculate_apparel_leadtime`) appear **only**
in the standalone GLTG repository, which is the intended source of truth.

## What was removed per repo

- **giraffe-agent**: `GLTG/` (vendored package), `src/gltg/` (engine),
  `src/lead_time/lead_time_calculator.py`, `src/lead_time/path_enumerator.py`.
  Replaced by `src/integrations/gltg_client.py` + `src/integrations/gltg_leadtime.py`
  (client-backed adapter; P80 feasibility basis; raises on GLTG failure).
- **abcdYi**: `libs/GLTG/`, the `gltg` path dependency + `uv.sources` entry,
  `src/lead_time/lead_time_calculator.py`, `src/lead_time/path_enumerator.py`.
  Replaced by `src/integrations/gltg_client.py`, `gltg_leadtime.py`, and a
  rewritten `gltg_adapter.py` that calls the API and maps to feasibility DTOs.
- **aivan**: `src/aivan/leadtime/` (local calculator/models/explainer). Rewrote
  `src/aivan/integrations/gltg.py` as a thin HTTP-backed facade; relocated
  lead-time DTOs to `aivan.schemas.leadtime`; removed the silent timeout fallback.
