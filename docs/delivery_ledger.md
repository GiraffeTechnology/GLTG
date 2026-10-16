# GLTG PRD delivery ledger

GLTG is deployed independently. Aivan calls its authenticated HTTP API. The
trade/processing PRD defines the model target; the rows below record executable
delivery work. Historical PRs are implementation inputs, not completion claims.

| Stage | Scope | Implementation and regression evidence | Status |
| --- | --- | --- | --- |
| 1 | Compatible candidate integration | Reconcile PRs 17 and 19 with current main; preserve tenant credentials, profile projection, assessment scope, canonical calculation and persistence idempotency; 374 tests passed, compile/pip check, five-run determinism and supplier cases passed | Verified locally; PR publication pending |
| 2 | Factor formulas and explanations | Close reproduced gaps in PRD sections 6-7 and scenarios A-D, preserving fractional days and provider numerical parity | Pending |
| 3 | Private-data mapping and durable run results | Map versioned evidence into factor inputs; persist and read back through the provider API; distinguish failed and unknown writes | Pending |
| 4 | Independent service acceptance and consumer handoff | Execute HTTP, negative identity, recovery and restart checks against selected actual services; publish precise consumer contract and results | Pending |

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
