# GLTG cross-owner alignment direction — 2026-09-08

Status: verified contract direction only. This is not an implementation, release, production-readiness, DB-backed execution, model-accuracy, or full-product acceptance claim.

Baseline referenced by the underlying evidence:

- GLTG runtime commit: `e370ae9a049171b3dd6e8a07e9d6e2beed5f69f7`
- GLTG runtime tree: `121a05e3b44a73c9f72a40e43481ae3e25498857`
- External R3 evidence manifest SHA-256: `D013678AC14721DAC0E4425D195208D99C077F35C1B207A4C1BC5D2F1C9201F3`

Accepted direction:

- The private data plane owns credential-bound source selection, source integrity, canonical unit normalization, immutable snapshot/read-proof/lease identity, and source lineage.
- GLTG owns the normalized-fact-to-model-feature projection contract, null/zero/omitted/default dispositions, deterministic algorithm, P50/P80/P90, canonical explanation codes, and result fingerprints.
- A DB-neutral private adapter may execute the exact GLTG-owned projection rule but may not redefine it.
- Aivan validates and transports the projection and passes an accepted GLTG result/reference onward. Aivan does not calculate GLTG values.
- Provider narrative is non-authoritative. For identical canonical numeric input and identical accepted algorithm/rule/calibration/model-artifact identity, provider narrative or execution metadata cannot change canonical numbers or GPM replay identity.
- A genuine versioned algorithm, model artifact, calibration, or numeric-policy change may change results, but must receive a new identity and independent evaluation.
- Hashes are domain- and version-tagged and independently recomputed. A digest from one domain cannot substitute for another; incidental equal bytes alone are not equivalence or failure.

PRD v2.0 delivery alignment:

- GLTG remains an Industrial Lead-Time Intelligence Engine responsible for simulation, P50/P80/P90, risk explanation, scenario comparison, and Aivan API integration.
- GLTG does not own workflow execution, commercial approval, raw-language understanding, or order-fact management.
- Requirements not mentioned by the scope reset remain in force unless an explicit conflict or explicit rescission exists. Component evidence does not replace full-product acceptance.

Known limits retained:

- Historical zero-versus-missing quantile correctness remains open in a separate RED test candidate.
- The minimal local vector used `use_giraffe_db=false`; it is component-synthetic and is not DB-backed evidence.
- No accepted private-DB integration release, real-provider run, server deployment, or real-business accuracy claim is represented here.
