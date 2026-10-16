# Independent GLTG deployment and acceptance

GLTG runs in its own process with its own source/deployment identity. Aivan
uses HTTP; it does not import the GLTG engine or replace a failed call with
a local estimate. Use the existing deployment's host, port, runtime and secret
store. Preserve occupied/reserved ports and other services.

Install `.[api]` into the GLTG runtime and start `gltg.api.main:app` with uvicorn.
Docker also supplies the independent runtime. Its `GLTG_HOST` and `GLTG_PORT`
settings determine the service binding. A bundled installer may supervise this
separate process without embedding it into the Aivan application process.

| Consumer / provider role | Setting or API |
| --- | --- |
| GLTG inbound service trust | `GLTG_INBOUND_SERVICE_AUTH_SECRET` |
| Aivan outbound service trust | `GLTG_SERVICE_AUTH_SECRET` |
| Aivan selected endpoint | `GLTG_API_BASE_URL` |
| Required v2 request headers | `X-Service-Auth`, `X-Service-Tenant-ID` |
| Tenant binding | Mandatory body `tenant_id` equals the authenticated header |
| Selected private-data endpoint | `GLTG_GIRAFFE_DB_BASE_URL` |
| Provider trust | `GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET` or `GLTG_GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON` |
| Run persistence | `GLTG_PERSIST_RUNS=true` |
| Simulation | `POST /v2/lead-time/simulate` |
| Comparison / updates | `POST /v2/paths/enumerate`, `POST /v2/reforecast` |
| Process / dependency probes | `GET /health`, `GET /ready` |

Use an existing secret store; do not include secret values in source, PRs,
shell arguments or evidence. Model/provider settings affect auxiliary
explanation only. The deterministic engine supplies all canonical numbers.

## Reproducible HTTP acceptance

`scripts/validate_private_provider_http.py` starts actual language, provider and
GLTG processes and executes the selected Aivan checkout's unmodified HTTP
client. It uses the fixed synthetic `tests/fixtures/prd_http_dataset_v1.json`
dataset, records source commit/tree/content hashes, and uses actual provider
APIs for all business writes and readback. It performs actual Alembic migrations
against the explicitly supplied isolated acceptance database.

Supply `--provider-repo`, `--language-repo`, `--consumer-repo`, and `--output`.
For MySQL, configure the isolated test DSN through
`GLTG_ACCEPTANCE_DATABASE_URL`; it is never printed. Do not supply a production
database as an isolated acceptance database. The optional
`--sqlite-supplement` mode uses a temporary database and is labeled as a
supplement, not as MySQL or CTYun acceptance.

Coverage includes scenarios A-D, real snapshot factor consumption and lineage,
ordered nonnegative quantiles, five repeated numerical/persistence identities,
effective idempotency, 401/403/raw non-ASCII rejection, zero writes on rejected
identity, provider-side 0/1/2/4 path comparisons, the Aivan client, DB/GLTG
restart readback, provider loss and child-process/workspace cleanup.

Rule `behavior-rules-v0.2.1` additionally binds deadline feasibility to the
returned canonical precision, revalidates event-updated inputs, and verifies
event source references before reforecasting. No statistical coverage or
real-business accuracy is claimed by this synthetic test.

## Rollback and handoff

Keep the current deployment and at most two verified usable rollback versions,
plus active build/acceptance inputs. Save source and artifact hashes, exact
configuration references, API compatibility and data receipts before an
authorized activation. A code rollback does not undo acknowledged business
writes. Reconcile indeterminate writes using their original key/receipt.
Operations archives and verifies recovery before deleting inactive server
artifacts. Evidence, databases, secret stores and shared runtimes remain
protected. A successful component test does not automatically merge a PR or
activate production.
