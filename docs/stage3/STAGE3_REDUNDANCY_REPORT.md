# Stage 3 — Redundancy Report (GLTG)

Each entry records path, reason, reference search, replacement/owner, and
validation. Search tool: `grep -rn` across the tree (excluding `.git`,
`__pycache__`), covering Python, YAML, TOML, Markdown, and shell.

## Removed / archived

| # | Path | Action | Reason / evidence | Validation |
| --- | --- | --- | --- | --- |
| R1 | `GLTG_AUDIT_2026-06-27.md` | moved to `docs/reports/` | stale root-level one-shot report; zero inbound references | suite green; docs-only |
| R2 | `MIGRATION_TEST_REPORT.md` | moved to `docs/reports/` | stale root-level report; single reference in `docs/migration_audit.md` updated to the new path | suite green |
| R3 | `GLTG_API_VERSION` env var | removed from `.env.example` and `docker-compose.yml` | never read: `grep -rn GLTG_API_VERSION src/ scripts/ tests/` → zero code matches | suite green; compose config-only |
| R4 | `GLTG_LOG_LEVEL` env var | removed from `.env.example` and `docker-compose.yml` | never read anywhere in code | suite green |
| R5 | CI env pinning `GLTG_EVALUATOR_MODE=llm` + mock provider | removed from workflow env | contradictory configuration: CI globally forced a non-default mode, so the shipped default path was never exercised; evaluator tests pin their own env explicitly | full suite green under shipped defaults (307 tests) |

## Audited and kept (not redundant)

| Path | Why kept |
| --- | --- |
| `src/gltg/evaluator/` (providers, prompts, guardrails) | real, tested, now strictly opt-in (`GLTG_EVALUATOR_MODE=llm`); removal would be a capability decision, not redundancy cleanup |
| `src/gltg/behavioral/simulator.py` | the default v2 engine (re-promoted in Stage 3) |
| v1 API + engine (`engine.py`, `graph/`, `estimation/`, `enumeration/`, `apparel/`, `reforecast/`, `packets/`) | live, tested compatibility surface; removal requires a consumer migration plan (none exists) — explicitly out of scope per the Stage 3 instruction |
| `scripts/verify_file_encoding.py` | self-documenting utility (referenced in its own usage docstring); harmless, one function, kept |
| `scripts/run_*.py`, `scripts/verify_gltg_5x.py` | all wired into CI |
| `examples/` | consumed by the acceptance scripts |
| `pyproject.toml` `[dependency-groups]` alongside `[project.optional-dependencies].dev` | intentional duplication: `dependency-groups` feeds `uv.lock`, the `dev` extra feeds pip installs (CI) — documented here rather than merged to avoid breaking either installer |
| `pyproject.toml` `cli = []` extra | empty but declares the console-script surface; zero cost |
| Dependencies (`pydantic`, `fastapi`, `uvicorn`, `httpx`, `respx`, `pytest*`) | all imported; `respx` used by adapter + Stage 3 integration tests; no unused dependency found |

## Duplicate DTO / formula audit

- v1 (`api/schemas.py`) and v2 (`behavioral/schemas.py`) DTOs are distinct
  contracts, not duplicates (different consumers; v1 kept for compatibility).
- The evaluator packet schema (`evaluator/schemas.py`) intentionally mirrors
  parts of the v2 response for the LLM interchange format; consolidation
  would couple the wire format of an experimental mode to the stable API.
- No duplicated formula implementations found: quantile composition,
  monotonic repair, and behavior tiers exist once, in
  `behavioral/simulator.py` (guarded by `tests/stage3/test_invariants.py`).
