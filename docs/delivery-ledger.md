# GLTG Delivery Ledger

This ledger tracks only the bounded GLTG work required for the current Aivan
workflow. A passing component test is not proof of complete Aivan integration or
production deployment.

| ID | Cause / reproduction | Owner | Actual fix | Regression evidence | Candidate | Status |
| --- | --- | --- | --- | --- | --- | --- |
| G01 | Feasibility fixtures used a fixed requested date but no evaluation date, so advancing wall time changed an expected `FEASIBLE` result to `REQUIRES_EXPEDITE`. | GLTG | Pin deterministic fixtures to an explicit `evaluation_date`; retain the strict `FEASIBLE` assertion. | `tests/e2e/test_reproducibility_5x.py`, `tests/integration/test_delivery_feasibility_packet.py`, and `tests/unit/test_no_exact_top3_requirement.py`; focused run: 35 passed. | Fix commit `c7dd9f38da6ce1286789cde8558950dca86e34e1`; current verification parent `f272a703f03570ea2ae404d85d79cb9ff47b7185`. | Reproduced cause; candidate fix locally verified. Not merged or deployed. |
| G02 | Strict numeric and tenant boundaries require verification on the selected combined candidate. Historical PR evidence is input, not a current result. | GLTG | Reuse compatible canonical-number and tenant-boundary work; resolve conflicts without weakening invariants. | Pending focused and full-suite verification on the combined candidate. | Pending selection/integration. | Open. |
| G03 | Real Aivan identity/fact inputs plus evidence consumption and evaluation persistence have not yet been demonstrated together on the selected final versions. | GLTG | Wire and test the actual authenticated consumer and persistence contracts; keep missing evidence missing. | Pending real-service HTTP, recovery, restart, and readback evidence. | Pending dependency coordination. | Open. |

