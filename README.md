# GLTG lead time module

GLTG is the API dependency that supplies lead-time calculation, simulation, path comparison and reforecasting to Aivan and other Giraffe Agent applications. Aivan is the frontend application for inquiry, quotation and order confirmation; abcdYi is the apparel and textile industry application whose frontend calls Aivan.

## Delivery objective

Use the original product descriptions and the supplied GLTG Trade and Processing Time Factor Model PRD to define the required outcomes. Return P50/P80/P90 estimates, feasible alternatives, material and capacity effects, risk explanations, and updated forecasts as relevant process evidence changes. Explain how a factor affects median lead time and tail uncertainty. Slow supplier response is not automatically low engagement; fast response is not automatically reliable.

The full source-aligned iteration specification is `docs/GLTG_TRADE_PROCESSING_TIME_FACTOR_MODEL_PRD.md`. Historical issue titles, prior implementation reports and installed algorithms do not independently redefine product scope or add delivery prerequisites.

## Responsibility boundary

- GLTG owns lead-time model behavior, scenario comparison and explanation.
- Aivan, abcdYi and Giraffe Agent call the module through its API; they do not copy its engine or silently substitute local estimates.
- The selected private DB supplies authoritative business history and current process evidence and records required model inputs, outputs and lineage. `giraffe-db` is a replaceable reference provider, not a mandatory vendor or physical DB identity.
- GPM owns its declared procurement/quote-guidance behavior through its API.
- Product workflows and human operators retain business execution and commercial approval.
- `giraffe-language-skill` supplies dynamic translation before business processing and for requested non-English output.

GLTG receives standard-English business input. The DB stores English business history, process records and results; only enterprise/user profile information may retain non-English values. Do not bypass this boundary by putting raw multilingual business content into evidence or audit fields.

## Acceptance data and evidence

The owner's two designated simulated databases are valid for product testing and acceptance. Preserve synthetic labels and source traceability. Actual selected API calls, contract handling, model behavior and relevant persistence still need to be exercised; skipped tests and mock transports are reported as such. Production customer records and a particular cloud or SQL vendor are not acceptance prerequisites.

P50/P80/P90 are model estimates. Do not describe them as empirically calibrated delivery guarantees without calibration evidence. The supplied PRD places statistical calibration after sufficient observations are available; it is not a prerequisite for the initial rule-based factor iteration.

## Current implementation snapshot

The deterministic engine supplies canonical P50/P80/P90. `GLTG_EVALUATOR_MODE=llm` explicitly enables auxiliary qualitative assessment; provider output cannot replace the numbers. Rule `behavior-rules-v0.4.0` includes staged trade/processing factors, capacity and material quantities, derived requirement/response ratios, explicit category/buyer/material duration parameters, separated median/tail explanations, canonical cutoff precision and validated reforecast inputs. Statistical calibration remains unperformed.

The v1 API and v2 API are described in `docs/api_reference.md` and `docs/gltg_v2_behavioral_contract.md`. Use `docs/integration_guide.md` for the API boundary. Historical engine/CLI fixtures remain useful provider-side assets; they do not authorize embedding the engine in Aivan.

See `docs/standalone_delivery.md` for independent deployment and reproducible real-HTTP acceptance, and `docs/delivery_ledger.md` for stage results and remaining environment-specific verification.

## License

See `LICENSE`.
