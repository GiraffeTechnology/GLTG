# GLTG staged delivery evidence — 2026-10-16

## Tested bounded candidate

- GLTG: `61092e07286d3925e1887ffde712105b568d37e2`, tree `bafdc98c6c901589baee379d534f0337aaf393da`.
- Reference provider: `ddbadf9038d70045e8ac8dac07903342a4c38d2c`, tree `77d4119a03e5c9b70ee81cd8cb1043bdadd7bfc3`.
- Selected Aivan HTTP consumer: `beaec23663e8b8e78f82b4b90cec33db2cd1d283`, unchanged.
- Language API: `c4efcaea7cddfe3653fda7b7a3d2076b1e3bc302`, unchanged.
- Rule: `behavior-rules-v0.4.0`; statistical calibration remains unperformed.

GLTG is an independent service. Aivan calls its HTTP API and does not embed its
calculation engine. The model supplies authoritative fractional P50/P80/P90;
optional providers do not replace canonical numbers, facts or identity.

## Implemented and tested

The stacked implementation PRs are #22 through #28. They preserve compatible
existing fixes and implement tenant/auth boundaries, provider-numeric isolation,
PRD factor formulas and derivations, median/tail explanations, private snapshot
mapping, effective idempotency, full evaluated-run persistence and API readback,
indeterminate write outcomes, date/cutoff precision and validated reforecasting.
Provider PR GiraffeTechnology/giraffe-db#38 supplies schema-bound English
validation of behavior protocol codes without bypassing free-text validation.

Local results on the fixed candidate:

- Full suite: 419 passed, zero skipped.
- Provider focused regressions: 67 passed.
- Changed-Python-file Ruff, high-severity Bandit, compilation, pip consistency,
  data-ID scan, supplier edge cases and five-run determinism: exit 0.
- Dependency audit: no known vulnerabilities after upgrading the isolated
  test environment's pip; this is not an audit of every target-server package.
- Clean API-only installation/import/HTTP smoke passed on the preceding
  runtime candidate. The final exact candidate also passed CI API-only smoke
  on Python 3.11, 3.12 and 3.13.
- Real-process language/provider/GLTG plus unmodified Aivan-client supplement:
  38 checks passed, including actual Alembic migrations, snapshot consumption,
  source lineage, 401/403/raw non-ASCII rejection, deterministic replay,
  effective idempotency, restart readback and provider-loss failure.

The supplement uses **SQLite**, not MySQL. Inputs are fixed synthetic business
scenarios, dataset `gltg-prd-http-synthetic-v1`, seed `20261016`; its bytes/hash
are in the machine evidence. No customer communications, orders or payments
were sent. This does not prove full Aivan business workflow acceptance or
real-business lead-time accuracy.

## CI and CTYun outcomes — not accepted

Exact-head CI run `38834732479`: Python 3.11/3.12/3.13 and Docker build/startup
passed. The required private HTTP job **failed** its credential preflight;
clone, verify, install and real HTTP steps were skipped, not passed. The
selected workflow now uses actual MySQL, language and consumer processes, but
its private-dependency read credential still needs configuration.

CTYun attempts ran between approximately 00:50 and 01:17 UTC. The latest
server-tested runtime candidate was `c13e9893546e7786df4fe5ec1de394b88fc5ead8`,
not the final formula-parameter candidate. Source/archive hashes were checked.
Missing legacy runtime dependencies were isolated into temporary paths; shared
runtimes and current services were not modified. A calculation against the old
provider was rejected for tenant identity mismatch. The selected provider was
then prepared for an isolated MySQL schema, but the configured application
account's schema creation was denied with MySQL error 1044. No grant escalation,
alternate privileged credential, production migration or permission bypass was
attempted. Required target migrations and the selected MySQL E2E did not run.

This is a concrete environment limitation, not a successful check or an
independent provider-product launch prerequisite. Resume with an existing
authorized isolated test schema/profile and the existing acceptance runner.

## Cleanup, rollback and release state

Target temporary candidate/provider units, dependencies, secret files and
workspaces were removed. Existing services and protected ports remained
unchanged. An early old-provider attempt created synthetic API records before
tenant rejection; they were not deleted by guessing ownership. No real
customer actions occurred. The latest local supplement cleaned up its processes
and workspace. A first failed local supplement's scratch was retained because
its cleanup command was rejected by platform policy; no alternate deletion was
attempted. Later successful cleanup is not evidence that the first scratch was
removed.

All implementation/evidence PRs remain open. No merge or production activation
occurred. Keep the current deployment for rollback; any acknowledged or
indeterminate business write requires receipt/key reconciliation, not code
rollback or an assertion of zero mutation.

`artifact-manifest.json` records this subset's exact bytes and SHA-256 values.
Private management scripts, credentials, host addresses, DSNs, environment
dumps, complete provider logs and customer data are excluded.
