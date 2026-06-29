# GLTG — Giraffe Lead-Time Graph

`Python 3.11+` | `GLTG v1.0.0` | `Deterministic Engine` | `FastAPI` | `CLI` | `Lead-Time Intelligence` | `AIVAN / giraffe-db Integration`

GLTG is the Giraffe Technology lead-time intelligence engine for apparel and textile execution. It calculates what can be delivered, when it can be committed, which supplier path is safer, and how the plan changes when new execution facts arrive.

GLTG is not an LLM prompt, not a spreadsheet formula, and not a generic delivery-date calculator. It is a standalone deterministic service that turns structured order facts, supplier capabilities, supplier confirmations, historical memory, progress events, logistics assumptions, and risk constraints into auditable delivery-feasibility results.

---

## The Problem

In apparel and textile trade, lead time is not a single number.

A realistic delivery promise depends on:

```text
material readiness
trims readiness
factory capacity
production queue
production speed
QC duration
packing
logistics mode
destination
supplier reliability
historical delay behavior
in-flight progress events
risk buffer
calendar assumptions
```

A salesperson or merchandiser may say “45 days,” but the execution system needs to answer a harder question:

```text
Can this order actually be delivered by the required date?
Which supplier path should be selected?
What confidence level should be used for commitment?
What changed after a supplier update or delay?
What evidence supports the answer?
```

That is the role of GLTG.

---

## What GLTG Is

GLTG is the standalone calculation authority for:

```text
lead-time estimation
supplier lead-time comparison
P50 / P80 / P90 planning bands
committable delivery date
most-likely delivery date
earliest feasible delivery date
risk-adjusted delivery date
single-source path ranking
parallel-split path ranking
reforecasting after progress events
structured warning generation
calculation trace generation
```

GLTG produces machine-readable outputs for agents and human-readable evidence for operators.

---

## What GLTG Is Not

GLTG does not own:

```text
buyer communication
supplier communication
RFQ/project state
human approval workflow
private business database persistence
IM/email account connectivity
platform login/session handling
legal, credit, sanctions, or trade-compliance decisions
```

Those belong to AIVAN, giraffe-db, OpenClaw, or human operators.

GLTG only answers the lead-time and execution-feasibility question.

---

## System Position

```text
Buyer / Operator instruction
        │
        ▼
      AIVAN
        │
        ├── parses RFQ
        ├── retrieves private context from giraffe-db / GPM
        ├── screens supplier risk
        └── calls GLTG for lead-time feasibility
                │
                ▼
              GLTG
                │
                ├── estimates lead time
                ├── ranks delivery paths
                ├── produces P50 / P80 / P90 bands
                ├── reforecasts when facts change
                └── returns structured trace
```

`giraffe-db` is the private business fact source. GLTG is the lead-time calculation source. AIVAN is the trade-execution entry point.

No consumer should duplicate GLTG logic or silently fall back to LLM-guessed lead times.

---

## Core Model

GLTG treats supplier lead time as an evidence-weighted execution graph, not a flat sum.

The simplified public API accepts four dominant stage durations:

```text
material_ready_days
production_days
qc_days
logistics_days
```

Internally, those map into the graph engine’s apparel workflow nodes. The engine then derives feasibility, delivery dates, confidence bands, warnings, and traces.

The HTTP layer also supports input preparation such as:

```text
capacity-adjusted production days
baseline stage synthesis when fields are missing
destination/logistics hints
explicit evaluation_date for deterministic tests
progress-event deltas for reforecasting
```

---

## Key Guarantees

1. GLTG is deterministic for the same input.
2. GLTG never invents suppliers to satisfy comparison requirements.
3. GLTG handles 0, 1, 2, and 3+ suppliers without crashing.
4. GLTG returns structured warnings instead of hiding weak evidence.
5. GLTG returns calculation traces that downstream agents can store in audit logs.
6. GLTG owns lead-time math; LLMs may explain results but must not replace them.
7. Human review remains required before any commercial commitment is sent to a counterparty.

---

## Supplier Count Rules

| Supplier count | Behavior |
|---:|---|
| `0` | Return infeasible result with `NO_SUPPLIERS`; do not crash. |
| `1` | Calculate with limited-comparison warning. |
| `2` | Calculate with limited-supplier-pool warning. |
| `3+` | Run normal supplier comparison and path enumeration. |

GLTG does not fabricate additional suppliers to reach three options.

---

## Install

```bash
git clone https://github.com/GiraffeTechnology/GLTG.git
cd GLTG
python -m pip install -e ".[dev]"
```

For API runtime only:

```bash
python -m pip install -e ".[api]"
```

With `uv`:

```bash
uv sync
```

---

## Run the Service

```bash
uvicorn gltg.api.main:app --host 0.0.0.0 --port 8090
```

Health:

```bash
curl http://localhost:8090/health
```

Version:

```bash
curl http://localhost:8090/version
```

Docker:

```bash
docker build -t giraffe-gltg .
docker run -p 8090:8090 giraffe-gltg
```

The Docker image honors:

| Variable | Default | Purpose |
|---|---|---|
| `GLTG_HOST` | `0.0.0.0` | API bind host. |
| `GLTG_PORT` | `8090` | API bind port. |

---

## HTTP API

Default base URL:

```text
http://localhost:8090
```

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check. |
| `GET` | `/version` | Service version and API version. |
| `POST` | `/v1/lead-time/estimate` | Estimate lead time, delivery dates, supplier feasibility, warnings, and calculation trace. |
| `POST` | `/v1/paths/enumerate` | Rank single-source and parallel-split delivery paths. |
| `POST` | `/v1/reforecast` | Apply progress-event deltas and return updated forecast. |

---

## API Input Shape

### Order

```json
{
  "product_type": "apparel",
  "quantity": 10000,
  "target_delivery_date": "2026-08-31",
  "evaluation_date": "2026-06-30",
  "destination": "Vancouver",
  "logistics_mode": "air",
  "deadline_days": 45
}
```

`evaluation_date` is optional, but recommended for deterministic tests and reproducible acceptance cases.

### Supplier

```json
{
  "supplier_id": "M1",
  "name": "Supplier M1",
  "capacity_per_day": 800,
  "material_ready_days": 5,
  "production_days": 14,
  "qc_days": 2,
  "logistics_days": 7,
  "confidence": 0.8
}
```

### Constraints

```json
{
  "allow_partial_suppliers": true,
  "min_supplier_count": 0,
  "currency": "USD"
}
```

---

## Lead-Time Estimate Example

```bash
curl -s http://localhost:8090/v1/lead-time/estimate \
  -H 'content-type: application/json' \
  -d '{
    "order": {
      "product_type": "apparel",
      "quantity": 10000,
      "target_delivery_date": "2026-08-31",
      "evaluation_date": "2026-06-30",
      "destination": "Vancouver",
      "logistics_mode": "air",
      "deadline_days": 45
    },
    "suppliers": [
      {
        "supplier_id": "M1",
        "name": "Supplier M1",
        "capacity_per_day": 800,
        "material_ready_days": 5,
        "production_days": 14,
        "qc_days": 2,
        "logistics_days": 7,
        "confidence": 0.8
      }
    ],
    "constraints": {
      "allow_partial_suppliers": true,
      "min_supplier_count": 0,
      "currency": "USD"
    }
  }'
```

Important response fields:

```text
estimated_lead_time_days
earliest_delivery_date
most_likely_date
committable_date
risk_adjusted_date
feasible
selected_supplier_id
supplier_count
p50_days
p80_days
p90_days
minimum_feasible_days
risk_level
on_time_probability
feasibility
warnings
calculation_trace
```

---

## Path Enumeration Example

```bash
curl -s http://localhost:8090/v1/paths/enumerate \
  -H 'content-type: application/json' \
  -d '{
    "order": {
      "product_type": "apparel",
      "quantity": 10000,
      "evaluation_date": "2026-06-30"
    },
    "suppliers": [
      {
        "supplier_id": "M1",
        "capacity_per_day": 800,
        "material_ready_days": 5,
        "production_days": 14,
        "qc_days": 2,
        "logistics_days": 7,
        "confidence": 0.8
      },
      {
        "supplier_id": "M2",
        "capacity_per_day": 600,
        "material_ready_days": 4,
        "production_days": 18,
        "qc_days": 3,
        "logistics_days": 8,
        "confidence": 0.7
      }
    ],
    "constraints": {
      "allow_partial_suppliers": true
    }
  }'
```

Path modes:

```text
SINGLE_SOURCE
PARALLEL_SPLIT
```

Paths are ranked deterministically by feasibility, lead time, confidence, and path ID.

---

## Reforecast Example

```bash
curl -s http://localhost:8090/v1/reforecast \
  -H 'content-type: application/json' \
  -d '{
    "order": {
      "product_type": "apparel",
      "quantity": 10000,
      "evaluation_date": "2026-06-30"
    },
    "suppliers": [
      {
        "supplier_id": "M1",
        "capacity_per_day": 800,
        "material_ready_days": 5,
        "production_days": 14,
        "qc_days": 2,
        "logistics_days": 7,
        "confidence": 0.8
      }
    ],
    "events": [
      {
        "supplier_id": "M1",
        "production_days_delta": 3,
        "note": "Factory queue delay"
      }
    ],
    "constraints": {
      "allow_partial_suppliers": true
    }
  }'
```

Progress events are additive deltas:

```text
positive delta = delay
negative delta = pull-in
```

---

## Python Engine Usage

```python
from gltg import LeadTimeGraphEngine, ApparelOrderInput

engine = LeadTimeGraphEngine()

order = ApparelOrderInput(
    order_id="ORD-001",
    product_type="men_shirt_cotton",
    quantity=10000,
    requested_delivery_date=None,
    dynamic_form={"fabric_type": "cotton", "wash_required": True},
    participants=[],
)

packet = engine.evaluate(order)

print(packet.status)
print(packet.commitable_date)
print(packet.critical_path)
print(packet.risk_flags)
```

Core engine operations:

```python
graph = engine.build_graph(order)
options = engine.enumerate_options(graph)
packet = engine.evaluate(order)
updated_packet = engine.reforecast(packet, events, evaluation_date=...)
```

---

## CLI

Evaluate an order:

```bash
gltg evaluate examples/10000_shirts_order.json --summary
```

Write a feasibility packet:

```bash
gltg evaluate examples/10000_shirts_order.json --output packet.json
```

Reforecast an existing packet:

```bash
gltg reforecast packet.json examples/10000_shirts_progress_events.json --summary
```

Important: CLI `reforecast` expects an existing serialized packet as the first argument, not the original order JSON.

Edge cases:

```bash
gltg evaluate examples/zero_suppliers.json --summary
gltg evaluate examples/one_supplier.json --summary
gltg evaluate examples/two_suppliers.json --summary
```

---

## Example Files

| File | Purpose |
|---|---|
| `examples/10000_shirts_order.json` | Full apparel order example with participants, memory, supplier responses, calendar, and dynamic form fields. |
| `examples/10000_shirts_participants.json` | Participant profiles extracted from the main order. |
| `examples/10000_shirts_supplier_memory.json` | Historical supplier memory records. |
| `examples/10000_shirts_progress_events.json` | Progress events for reforecast testing. |
| `examples/zero_suppliers.json` | Empty supplier case. |
| `examples/one_supplier.json` | Single supplier case. |
| `examples/two_suppliers.json` | Two supplier case. |

---

## Tests

Run unit/integration/API tests:

```bash
pytest
# or
uv run pytest
```

Acceptance scripts:

```bash
python scripts/verify_gltg_5x.py
python scripts/run_zero_one_two_supplier_cases.py
python scripts/run_10000_shirts_acceptance.py
python scripts/run_api_edge_cases.py
```

Recommended pre-release check:

```bash
pytest
python scripts/verify_gltg_5x.py
python scripts/run_api_edge_cases.py
python scripts/run_zero_one_two_supplier_cases.py
python scripts/run_10000_shirts_acceptance.py
```

---

## Acceptance Criteria

A GLTG release is acceptable only when:

1. Standalone install succeeds.
2. API service exposes all five public endpoints.
3. 0/1/2/3+ supplier cases do not crash.
4. Outputs include structured warnings and calculation traces.
5. Repeated deterministic tests produce stable results.
6. Consumer repositories use GLTG through `GLTG_API_BASE_URL` instead of vendored logic.
7. No LLM replaces GLTG calculations.

---

## Integration Rules for AIVAN / giraffe-agent / abcdYi

Consumers configure:

```bash
GLTG_API_BASE_URL=http://localhost:8090
GLTG_API_TIMEOUT_SECONDS=30
```

Consumer clients should:

```text
validate request shape
send JSON with explicit timeout
return structured ok/data/error/status_code result
persist GLTG trace in decision packets or execution logs
surface GLTG warnings to the operator
avoid local fallback calculation
avoid LLM-generated lead-time replacement
```

GLTG results may be explained by an LLM after calculation, but the calculation itself must come from GLTG.

---

## Relationship with giraffe-db

`giraffe-db` stores private-domain facts and synthetic/private testing data:

```text
historical_quotes
leadtime_observations
supplier_capacity_snapshots
supplier response packets
risk_events
execution_events
system-generated records
```

GLTG consumes structured lead-time evidence derived from those records. It should not pretend synthetic records are real transaction history, and it should not invent missing facts.

---

## Why This Matters

AIVAN can draft a buyer response, but only GLTG should decide whether the delivery plan is feasible.

That separation is the core architecture:

```text
LLM = language, strategy explanation, operator interface
Giraffe DB = private business facts and evidence
GLTG = deterministic lead-time feasibility calculation
AIVAN = controlled trade-execution workflow
Human = final approval and legal/commercial responsibility
```

---

## Documentation

| Doc | Description |
|---|---|
| `docs/model_spec.md` | Full model specification. |
| `docs/evidence_weighting.md` | Evidence hierarchy and weighting. |
| `docs/apparel_node_templates.md` | Apparel node templates. |
| `docs/path_enumeration.md` | Path enumeration algorithm. |
| `docs/reforecasting.md` | Reforecast after progress events. |
| `docs/integration_guide.md` | Consumer integration guide. |
| `docs/api_reference.md` | HTTP API reference. |
| `docs/acceptance_criteria.md` | v1.0 acceptance criteria. |
| `docs/glossary.md` | Terminology glossary. |

---

## Limitations in v1.0

1. Calendar support uses simple working-day arithmetic.
2. Multi-region holiday calendars are not yet fully modeled.
3. On-time probability uses an approximation over P50/P80/P90 bands.
4. Path enumeration does not yet support full mixed-factory graph branching.
5. Human review is still required before commercial commitment.

---

## Next Iteration

1. Monte Carlo delivery probability simulation.
2. Multi-region supplier calendar support.
3. Timezone-aware scheduling.
4. Mixed-factory graph branching with cost modeling.
5. Live webhook-based reforecast triggers.
6. Buyer-portal output adapter.

---

## License

See `LICENSE`.
