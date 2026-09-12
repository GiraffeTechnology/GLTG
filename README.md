# GLTG — Industrial Lead-Time Intelligence Engine

`Python 3.11+` | `GLTG v1.0.0` | `FastAPI` | `Lead-Time Simulation` | `P50/P80/P90`

## Product Positioning

GLTG is Giraffe Technology's industrial lead-time intelligence engine.

It evolved from a simple Lead Time Graph into a delivery risk prediction and simulation engine for industrial execution workflows.

This repository follows:

**PRD v2.0 Product Scope Reset — GLTG Industrial Lead-Time Intelligence Engine**

See GitHub Issue #12 for the frozen product baseline.

---

## Previous PRD Definition

Original positioning:

```
GLTG = Lead Time Graph
```

Original objectives:

- Calculate delivery cycles based on supply chain nodes;
- Output order delivery feasibility.

---

## Current Product Scope

GLTG is responsible for:

- Delivery time simulation;
- Risk prediction;
- Supply chain path comparison;
- Behavioral factor adjustment;
- Delivery scenario explanation.

GLTG is not responsible for:

- Workflow execution;
- Commercial approval;
- Raw language understanding;
- Order fact management.

---

## System Boundary

```
Canonical Order Data
        ↓
      GLTG
        ↓
Lead-Time Simulation
        ↓
Risk / Scenario Output
        ↓
Aivan Execution Layer
```

Component ownership:

- GLTG = lead-time intelligence
- giraffe-db = business facts and evidence
- Aivan = execution workflow
- Human operator = commercial decision

---

## Core Capability

GLTG provides:

```
P50 = median planning lead time
P80 = conservative planning lead time
P90 = high-confidence planning lead time
```

It explains:

- Why delivery risk changed;
- Which supplier or buyer behavior affected forecast;
- Whether fallback suppliers are required;
- Whether human review is required.

---

## v1.0 Frozen Delivery Scope

Must complete:

1. Lead-Time Simulation
2. P50/P80/P90 output
3. Risk Explanation
4. Scenario Comparison
5. Aivan API Integration

---

## Prohibited Scope Expansion

During v1.0, do not add:

- Generic AI Agent capabilities;
- Workflow control layer;
- Commercial transaction system;
- Unvalidated ML/Bayesian model replacement of the deterministic engine.

---

## Running the Service

Run service:

```bash
export GLTG_INBOUND_SERVICE_AUTH_SECRET='replace-with-secret-manager-value'
uvicorn gltg.api.main:app --host 0.0.0.0 --port 8090
```

Every v2 request requires authenticated service headers. `tenant_id` is
mandatory in the JSON body and must exactly match the authenticated tenant;
the body never selects tenant identity.

```text
X-Service-Auth: <GLTG_INBOUND_SERVICE_AUTH_SECRET>
X-Service-Tenant-ID: <authenticated-tenant>
```

### giraffe-db evidence and persistence

giraffe-db is the canonical evidence service. Configure:

```bash
GLTG_GIRAFFE_DB_BASE_URL=http://giraffe-db:8000
GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET=...   # sent as X-Service-Auth, never logged
GLTG_PERSIST_RUNS=true                    # optional run persistence
```

A v2 request with `"evidence": {"use_giraffe_db": true}` retrieves the
tenant-scoped supplier record and behavior summary
(`X-Service-Tenant-ID` = request `tenant_id`). A configured giraffe-db URL
without a service-auth secret fails before transport, and every supplier,
behavior-summary, and persistence response must echo the same tenant. Failures are explicit:
unreachable giraffe-db → HTTP 503 `DB_UNAVAILABLE`; rejected auth/tenant →
HTTP 502 `EVIDENCE_AUTH_FAILED` (fail closed); missing supplier/behavior →
`EVIDENCE_NOT_FOUND` / `MISSING_BEHAVIOR_EVIDENCE` warnings with reduced
confidence. GLTG never invents evidence and has no silent mock fallback.
End-to-end proof: `scripts/validate_gltg_giraffe_db_e2e.py`.

### v2 response fields:

```text
gltg_run_id
model_version
rule_version
calibration_version
quantiles.p50_days
quantiles.p80_days
quantiles.p90_days
components.base_production_days
components.base_procurement_days
components.supplier_response_buffer_days
components.supplier_uncertainty_buffer_days
components.buyer_decision_buffer_days
components.logistics_buffer_days
components.risk_buffer_days
risk.deadline_risk_level
risk.confidence_score
risk.fallback_supplier_required
risk.manual_review_required
risk.deadline_feasible
risk.selected_confidence_days
explanation_json
warnings
persistence
source_observation_ids
```

---

## Core Principle

All future development must:

1. Map to the PRD scope;
2. Have explicit Acceptance Criteria;
3. Move toward production-ready delivery;
4. Not use algorithmic complexity as a substitute for delivery.

---

## License

See `LICENSE`.
