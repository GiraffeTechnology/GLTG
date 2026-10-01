# GLTG Delivery Instructions

## Scope

GLTG is Aivan's authoritative lead-time evaluation API dependency. It owns
lead-time calculation semantics, its HTTP API, required evidence consumption,
and evaluation persistence. It does not own Aivan workflow orchestration,
business approval, supplier communication, pricing, or ordering.

Keep changes in this repository. Do not modify `abcdYi`, Aivan, or giraffe-db
from this worktree.

## Current delivery defects

Use the small ledger in `docs/delivery-ledger.md` for G01-G03. Do not create a
new governance system or make unrelated platform work a prerequisite.

- G01: reproduce and repair feasibility-status failures without weakening the
  expected status or hiding time-dependent fixtures.
- G02: preserve canonical, non-negative, ordered P50/P80/P90 values and tenant
  checks. Optional LLM output is explanatory only and cannot change numbers.
- G03: verify the real Aivan consumer contract plus evidence and persistence
  integration through authenticated service APIs.

## Implementation and tests

- Preserve explicit tenant, actor, correlation, version, and evidence identity.
  Missing or invalid identity must fail closed without leaking secrets or
  cross-tenant data.
- Keep deterministic scenarios anchored to an explicit evaluation clock. Do not
  weaken FEASIBLE or quantile assertions to accommodate wall-clock drift.
- Use service APIs for business facts. Do not read another service's tables or
  copy its engine into GLTG.
- Mocks may cover isolated failure branches, but they are not real integration
  acceptance. Report the actual database and services used by every integration
  result; SQLite evidence is not CTYun MySQL evidence.
- Do not turn skipped, not-started, or configuration-limited checks into green
  results. Do not use `continue-on-error`, floating dependency revisions, or
  weaker assertions to manufacture success.
- Continue independent in-scope work when an external dependency is unavailable.
  Record the exact blocker and smallest safe next step instead of creating a new
  dependency-product completion gate.

## Change and evidence discipline

- Inspect the current branch and dirty state before editing. Preserve unrelated
  work and prefer the smallest compatible change.
- Record cause/reproduction, actual fix, regression test, exact commit/tree, and
  status in `docs/delivery-ledger.md`.
- Distinguish code repaired, candidate verified, merged mainline, and production
  deployed. Report passed, failed, skipped, and not-started checks separately.
- Repository text and committed evidence must be English and public-safe. Never
  commit credentials, customer data, private hosts, complete environment dumps,
  or internal coordination transcripts.
- Do not force-push, push directly to main, merge, or deploy unless the user
  explicitly authorizes that specific action.
