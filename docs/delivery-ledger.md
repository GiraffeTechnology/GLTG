# GLTG Delivery Ledger

GLTG is an independently deployable lead-time service. Aivan consumes it only
through the authenticated HTTP API; GLTG does not import Aivan or own Aivan's
workflow and approval state.

| ID | Cause and reproduction | Owner | Fix | Regression evidence | Status |
|---|---|---|---|---|---|
| G01 | Aivan's v2 HTTP payload included a typed `assessment_scope`, but GLTG discarded the field. | GLTG | Preserve and validate the two supported scope values in `GLTGCaseContext`. | `tests/s1/test_aivan_consumer_contract.py` | Repaired locally |
| G02 | The service boundary needed an executable guard against accidental in-process Aivan coupling. | GLTG | Add an AST-based runtime import boundary test. | `tests/s1/test_service_independence.py` | Repaired locally |
| G03 | The existing real-service runner did not exercise Aivan's current thin HTTP client. | GLTG | Optionally invoke that client against live GLTG and giraffe-db services when `AIVAN_REPO` is supplied. | `scripts/validate_gltg_giraffe_db_e2e.py` | Repaired locally |

Local real-service evidence uses an isolated SQLite database created through the
real giraffe-db migration chain. It proves the HTTP contracts and recovery
behavior, but it is not CTYun MySQL acceptance, a production deployment, or a
claim of real-world lead-time accuracy.
