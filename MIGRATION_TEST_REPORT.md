# GLTG Migration Test Report

Verification of the GLTG standalone migration and consumer integration.

## Environment

- Python 3.11
- GLTG installed editable with `pip install -e ".[dev]"`
- Live GLTG server: `uvicorn gltg.api.main:app --host 0.0.0.0 --port 8090`
- Consumers run against `GLTG_API_BASE_URL=http://localhost:8090`

## Exact commands

```bash
# GLTG
cd GLTG
python -m pip install -e ".[dev]"
python -m pytest -q                                   # 154 passed
python scripts/run_api_edge_cases.py                  # 0/1/2/3+ suppliers
python scripts/verify_gltg_5x.py                      # determinism
python scripts/run_zero_one_two_supplier_cases.py     # engine edge cases
uvicorn gltg.api.main:app --host 0.0.0.0 --port 8090  # live API
curl http://localhost:8090/health
curl http://localhost:8090/version

# giraffe-agent
cd giraffe-agent && python -m pytest -q               # 735 passed
GLTG_API_BASE_URL=http://localhost:8090 RUN_GLTG_INTEGRATION_TESTS=1 \
  python -m pytest tests/test_gltg_client_integration.py -q   # 2 passed (live)

# abcdYi
cd abcdYi && DATABASE_URL="sqlite+aiosqlite:///./t.db" SECRET_KEY=test \
  python -m pytest tests/unit -q -m "not integration"  # 463 passed, 2 skipped
GLTG_API_BASE_URL=http://localhost:8090 RUN_GLTG_INTEGRATION_TESTS=1 \
  python -m pytest tests/unit/test_gltg_client_integration.py -q  # 2 passed (live)

# aivan
cd aivan && python -m pytest -q                        # 416 passed, 2 skipped
GLTG_API_BASE_URL=http://localhost:8090 RUN_GLTG_INTEGRATION_TESTS=1 \
  python -m pytest tests/test_gltg_client_integration.py -q  # 2 passed (live)
```

## Full verification, 5 runs

Each run = GLTG unit + API tests, GLTG API edge cases (0/1/2/3+ suppliers),
5x determinism check, and engine zero/one/two supplier cases.

```
Run 1/5: PASS  (gltg: 154 passed | edge: PASS | 5x: PASS | 0/1/2: PASS)
Run 2/5: PASS  (gltg: 154 passed | edge: PASS | 5x: PASS | 0/1/2: PASS)
Run 3/5: PASS  (gltg: 154 passed | edge: PASS | 5x: PASS | 0/1/2: PASS)
Run 4/5: PASS  (gltg: 154 passed | edge: PASS | 5x: PASS | 0/1/2: PASS)
Run 5/5: PASS  (gltg: 154 passed | edge: PASS | 5x: PASS | 0/1/2: PASS)
```

**Run 1/5: PASS**
**Run 2/5: PASS**
**Run 3/5: PASS**
**Run 4/5: PASS**
**Run 5/5: PASS**

No failures were observed across the five runs; results were byte-stable
(determinism check spread = 0 days).

## Supplier edge cases (API)

| Suppliers | feasible | estimated_lead_time_days | warnings | paths |
|-----------|----------|--------------------------|----------|-------|
| 0 | false | null | `NO_SUPPLIERS` | 0 |
| 1 | true | 28 | `LIMITED_COMPARISON` | 1 |
| 2 | true | 28 | `LIMITED_SUPPLIER_POOL` | 3 |
| 3+ | true | 28 | (none) | 5 |

No crash in any case.

## Live API integration calls (consumer -> GLTG)

Each consumer repo made real HTTP calls to the running GLTG server
(`/health` + `/v1/lead-time/estimate` + zero-supplier case):

- giraffe-agent: `tests/test_gltg_client_integration.py` -> 2 passed
- abcdYi: `tests/unit/test_gltg_client_integration.py` -> 2 passed
- aivan: `tests/test_gltg_client_integration.py` -> 2 passed

## Consumer suites (regression)

| Repo | Result |
|------|--------|
| giraffe-agent | 735 passed (730 baseline + 5 new client tests) |
| abcdYi | 463 passed, 2 skipped (unit, sqlite; +5 client tests) |
| aivan | 416 passed, 2 skipped (411 baseline + 5 client tests) |

## Known gaps / remaining work

The standalone GLTG service, its API, edge-case handling, Docker packaging, and
the consumer HTTP clients are complete and verified. The deep removal of the
remaining in-tree calculators is intentionally staged as follow-up so the
consumer suites stay green during migration:

- **giraffe-agent**: `src/gltg/`, `src/lead_time/` and their callers
  (`src/b_side/feasibility_engine.py`, `src/m_side/rollup/supplier_response_rollup.py`)
  still compute locally. They must be rewired to the API client. ~24 test files
  assert the local p50/p80/p90 algorithm and need migration alongside.
- **abcdYi**: `libs/GLTG/` and `src/lead_time/` callers
  (`delivery_feasibility_service`, `decision_packets/service`) still use the
  vendored engine.
- **aivan**: `src/aivan/leadtime/` and the `GLTGClient` facade in
  `integrations/gltg.py` still calculate locally (and the facade has a silent
  timeout fallback that must be removed once the HTTP client is wired in).

These require porting each consumer's exact algorithm expectations onto the GLTG
API responses and updating the corresponding test expectations — a substantial
follow-up that should land per-repo to keep each suite green.
