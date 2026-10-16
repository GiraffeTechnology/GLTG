# GLTG PRD delivery ledger

GLTG is deployed independently. Aivan calls its authenticated HTTP API. The
trade/processing PRD defines the model target; the rows below record executable
delivery work. Historical PRs are implementation inputs, not completion claims.

| Stage | Scope | Implementation and regression evidence | Status |
| --- | --- | --- | --- |
| 1 | Compatible candidate integration | Reconcile PRs 17 and 19 with current main; preserve tenant credentials, profile projection, assessment scope, canonical calculation and persistence idempotency; 374 tests passed, compile/pip check, five-run determinism and supplier cases passed | PR 22 open |
| 2 | Factor formulas and explanations | Capacity, material quantity coverage, engagement separation, booking/customs/rework formulas, component accounting and median/tail explanations; new regression vectors RED 10 failed/1 passed, GREEN 11 passed; full suite 385 passed; focused Ruff and high-severity Bandit passed | Verified locally |
| 3 | Private-data mapping and durable run results | Validate and map snapshot factors/source IDs, persist complete evaluated results, scope replay by rule version, API case-graph readback, distinguish unknown writes; RED 7 failed/1 passed, GREEN 8 passed; full suite 393 passed | Verified locally; real HTTP in progress |
| 4 | Independent service acceptance and consumer handoff | 396 local tests; 38 actual language/provider/GLTG/Aivan-client HTTP checks passed on an explicitly labeled SQLite supplement, with migrations, API readback and restart. MySQL/CTYun acceptance remains separate | Component verification passed; target verification in progress |
| 5 | Remaining derived-input and missing-capacity semantics | Requirement completeness counts, response timing baseline hierarchy, finite numerical inputs, explicit date clocks, preserved supplier production facts and category fallback; 13 focused tests passed and 409 full-suite tests passed | Local verification passed |

Statistical calibration requires sufficient observed outcomes as specified in
PRD phase 6. Rule-based and synthetic integration results do not establish
real-world quantile coverage. CI may run while the next stage is implemented;
failed, skipped and unavailable checks remain separately reported.

## Reproduced issues

| ID | Cause / reproduction | Owner | Fix / test | Status |
| --- | --- | --- | --- | --- |
| G01 | Main lacks inbound v2 tenant/auth boundary present in candidate PR 19 | GLTG | Preserve authenticated tenant matching, raw non-ASCII rejection, and evidence-reference tests during integration | Local regression passed |
| G02 | Main permits provider output to influence canonical numbers; existing PR 17 has deterministic-only composition and numerical tests | GLTG | Reuse canonical provider-parity and component-composer implementation | Local regression passed |
| G03 | Existing branches each contain useful provider, evidence and persistence fixes not present together on main | GLTG | Preserve tenant-specific credentials, profile projection, assessment scope and effective idempotency | Local regression passed |
| G04 | Shared graph test helper used the wall clock; October execution incorrectly expired positive fixtures, causing 14 failures and 4 skips | GLTG | Pin the helper's evaluation date to 2026-01-01 without changing deadlines or assertions | 374 passed, zero skipped |
| G05 | Hidden unrounded quantiles disagreed with returned cutoff precision; reforecast accepted invalid factors and unowned event references | GLTG | Three RED tests became GREEN; round before feasibility, revalidate updated input and resolve event lineage | Local regression passed |
| D-GLTG | Real language API abstained on schema-defined short behavior/factor/assessment codes, rejecting actual provider writes | giraffe-db | Separate provider PR supplies finite identity-bound validation projections while retaining stored codes and free-text validation | 67 focused provider tests and 38 HTTP supplement checks passed |
