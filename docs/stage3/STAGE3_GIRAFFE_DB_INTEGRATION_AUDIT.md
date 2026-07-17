# Stage 3 — giraffe-db Integration Audit (read-only, pre-change)

Date: 2026-07-17.

## Pre-Stage-3 state: NOT_IMPLEMENTED

Search evidence (whole tree, case-insensitive): no module in `src/gltg`
performs any giraffe-db call. There is no giraffe-db client, no
`X-Service-Auth` / `X-Service-Tenant-ID` header anywhere, no evidence
retrieval, and no persistence write. The only occurrences of "giraffe-db"
are docstrings/comments, the response field name
`persisted_to_giraffe_db` (hard-coded `False` with warning
`PERSISTENCE_NOT_CONFIGURED` — honest), and the README badge
"`giraffe-db Evidence`" (aspirational). `integrations/aivan_client.py` and
`integrations/giraffe_agent_adapter.py` talk to AIVAN/giraffe-agent shapes,
not giraffe-db. `tenant_id` is accepted on v2 requests
(default `"tenant_default"`) but propagated nowhere.

Consequences for the Stage 3 requirements:

| Requirement | Pre-Stage-3 status |
| --- | --- |
| Retrieve supplier record | NOT_IMPLEMENTED |
| Retrieve supplier behavior summary | NOT_IMPLEMENTED |
| Lead-time / capacity / buyer evidence | NOT_IMPLEMENTED (accepted only as caller-supplied request fields) |
| Source observation IDs | pass-through of caller-supplied list only; never fetched, never invented |
| Auth fail-closed, tenant isolation | n/a (no calls existed) |
| `DB_UNAVAILABLE` on timeout, 404 → missing-evidence warning | n/a |
| Persist runs to giraffe-db | NOT_IMPLEMENTED (honestly reported as not persisted) |

## Counterpart surface available in giraffe-db (Stage 2A tree)

Verified against the giraffe-db Stage 2A branch (this session's PR #14
tree; task statement says Stage 2A is merged to main):

- `GET /api/data/suppliers/{supplier_id}` — tenant-scoped supplier record
  incl. `is_synthetic`, capability/material arrays, scores.
- `GET /api/data/suppliers/{supplier_id}/behavior-summary` — observation
  count, latest snapshot, response-delay ratio derivation (truthfully empty
  when no behavior data imported).
- `GET /api/data/suppliers` — bounded tenant-scoped listing.
- `POST /api/data/gltg-simulation-runs` — persistence target
  (`gltg_simulation_runs`: quantiles, components, `output_json`, required
  non-empty `explanation_json`; PK `gltg_run_id` is **assigned by
  giraffe-db** in canonical `GDB_SYN_V1_GLTG_......` form when omitted —
  GLTG's internal `GLTG_<sha1>` id is *not* valid there and must be carried
  in the payload, not as the PK).
- `POST /api/data/gltg-behavior-inputs` — behavior-input lineage records.
- Auth: `X-Service-Auth` (+`GIRAFFE_DB_SERVICE_AUTH_SECRET`) and
  `X-Service-Tenant-ID`; fail-closed 401/403; wrong tenant reads 404.

**Documented gap (giraffe-db side):** there is no
`GET /api/data/gltg-simulation-runs/{gltg_run_id}` route; persisted runs are
only readable via the procurement-case transaction graph. Stage 3 verifies
persistence through the create response (which returns the stored row) and
records this read-path gap here rather than inventing an endpoint. A
follow-up minimal giraffe-db PR can add the GET route.

## Stage 3 integration design (implemented after this audit)

- New `src/gltg/integrations/giraffe_db_client.py`: httpx-based client;
  `GIRAFFE_DB_BASE_URL`, `GIRAFFE_DB_SERVICE_AUTH_SECRET` (redacted in
  repr/logs), per-call tenant; bounded timeout
  (`GIRAFFE_DB_TIMEOUT_SECONDS`, default 5s); no retry storms (single
  retry on connect errors only); errors mapped to explicit codes:
  `DB_UNAVAILABLE` (timeout/transport), `EVIDENCE_AUTH_FAILED` (401/403),
  `EVIDENCE_NOT_FOUND` (404), `EVIDENCE_MALFORMED` (schema validation).
  **No silent mock fallback**: if evidence is requested and the client is
  unconfigured, the simulation returns an explicit warning and
  `evidence_status="unavailable"` — it never fabricates evidence.
- v2 request gains `evidence: {use_giraffe_db: bool, supplier_id, …}`;
  when enabled GLTG fetches the supplier record + behavior summary, maps
  observed fields into behavior features (only fields actually present),
  extends `source_observation_ids` with IDs returned by giraffe-db (never
  invented), and surfaces missing evidence as warnings with lower
  confidence inputs.
- Optional persistence (`GLTG_PERSIST_RUNS=true` + configured client):
  POST the run to `/api/data/gltg-simulation-runs`; `persistence.status` ∈
  `persisted | skipped | failed | unavailable` and never claims success it
  didn't observe.
- Real-HTTP proof: `scripts/validate_gltg_giraffe_db_e2e.py` (fresh
  giraffe-db DB → migrations → synthetic supplier import → live giraffe-db
  uvicorn → live GLTG uvicorn → authenticated evidence retrieval → v2
  simulation → persisted run → verification), using
  `GDB_SYN_V1_SUP_000001`. Results in `STAGE3_FINAL_VALIDATION.md`.
