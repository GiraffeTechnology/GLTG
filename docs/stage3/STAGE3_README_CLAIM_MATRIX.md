# Stage 3 — README Claim Matrix (audited against code, pre-change)

Classification values: `IMPLEMENTED`, `PARTIALLY_IMPLEMENTED`, `MOCK_ONLY`,
`NOT_IMPLEMENTED`, `UNVERIFIED`.

| README claim (pre-Stage-3 text) | Classification | Evidence |
| --- | --- | --- |
| Badge: "Deterministic Engine" | PARTIALLY_IMPLEMENTED | v1 engine and the v2 behavioral simulator are deterministic, but the shipped v2 **default** routes through an external LLM; deterministic engine is reachable only via fallback mode |
| Badge: "giraffe-db Evidence" | NOT_IMPLEMENTED | no giraffe-db client, no evidence retrieval, no persistence anywhere in `src/` |
| Badge: "Behavioral Adjustment" | IMPLEMENTED | `behavioral/simulator.py` adjustment rules (response delay, completeness, revisions, load, buyer volatility/decision delay, historical error), each explained |
| Badge: "Statistical Baseline" | PARTIALLY_IMPLEMENTED | historical P50/P80/P90 baseline is consumed when supplied by the caller; no category/route/pair baseline retrieval exists (no data source wired) |
| "v1 HTTP API — Implemented" | IMPLEMENTED | live-executed; CI curls all three endpoints |
| "v1 lead-time estimate — Implemented" | IMPLEMENTED | real graph-engine computation (not stage sums) |
| "v1 path enumeration — Implemented" | IMPLEMENTED | single-source + parallel-split, deterministic ranking |
| "v1 reforecast — Implemented" | IMPLEMENTED | events applied to stage days, delta disclosed |
| "v2 `/v2/lead-time/simulate` — Target / in progress" | PARTIALLY_IMPLEMENTED | route exists and executes; default path is LLM-projection (external), deterministic path demoted to fallback; honest per the README's own "in progress" label |
| "Statistical baseline — Target / in progress" | PARTIALLY_IMPLEMENTED | as above |
| "Behavioral adjustment layer — Target / in progress" | IMPLEMENTED | deterministic rules exist and are tested |
| "giraffe-db persistence — Target / in progress" | NOT_IMPLEMENTED | hard-coded `persisted_to_giraffe_db=False` + honest warning |
| "ML / Bayesian calibration — Later phase" | NOT_IMPLEMENTED (as stated) | `calibration_version="none"` — honest |
| System boundary: "GLTG does not own … outbound messages, approval, RFQ state" | IMPLEMENTED | no such capability in code |
| P0 language boundary (canonical English structured input only) | IMPLEMENTED (by construction) | GLTG parses structured DTOs only; no raw-text extraction paths |
| Core model: T_total decomposition of 9 stages | PARTIALLY_IMPLEMENTED | all stages exist as components; `T_quote_confirmation` has no dedicated component (folded into supplier response/uncertainty buffers) |
| "Distributional output P50/P80/P90" | IMPLEMENTED | three composers + monotonic repair |
| Target architecture: "giraffe-db behavior materialization" inputs | NOT_IMPLEMENTED | features accepted only from the caller; never fetched |
| Target architecture: "Persisted GLTG run" | NOT_IMPLEMENTED | see persistence above |
| Behavioral feature inputs (supplier/buyer/pair lists) | PARTIALLY_IMPLEMENTED | supplier features: all consumed; buyer: `requirement_change_count`, `buyer_decision_delay_score` consumed, others accepted but unused (`buyer_response_delay_ratio`, `price_negotiation_intensity`, `historical_rounds_to_po`, `conversion_probability`); pair: only `relationship_strength_score` used |
| Supplier count rules table (0/1/2/3+) | IMPLEMENTED | v1: warnings + no crash, tested; v2 paths: enumeration over provided list only (never invents suppliers) |
| "Current tests" commands | IMPLEMENTED | all listed scripts exist and run in CI |
| Acceptance criterion 9: "AIVAN and giraffe-agent can select v1 or v2 without local fallback" | UNVERIFIED | consumer-side behavior; not testable in this repo |
| Acceptance criterion 10: "LLMs do not replace GLTG calculations" | **CONTRADICTED BY CODE** | the default v2 path delegates quantile production to an LLM; deterministic rules are explicitly "demoted" (module docstrings). Classified NOT_IMPLEMENTED pre-Stage-3; fixed by Stage 3 (deterministic default, LLM strictly opt-in) |
| Expected v2 response fields incl. `source_observation_ids`, `persistence` | PARTIALLY_IMPLEMENTED | `source_observation_ids` missing at top level; `persistence` lacks truthful status enum |

The README is corrected in this same Stage 3 PR to match the
post-implementation reality (deterministic default, explicit LLM opt-in,
real giraffe-db evidence + persistence paths, and honest
implemented/experimental/planned labeling).
