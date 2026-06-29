# GLTG — Giraffe Lead-Time Graph

`Python 3.11+` | `GLTG v1.0.0` | `Deterministic Engine` | `FastAPI Service` | `CLI` | `AIVAN / giraffe-agent / abcdYi Integration`

GLTG is the standalone source of truth for apparel and textile lead-time calculation, execution-path enumeration, and delivery reforecasting across the Giraffe Technology stack.

It is not a simple lead-time calculator. GLTG converts order requirements, supplier capabilities, supplier confirmations, progress events, historical memory, logistics assumptions, and constraints into evidence-weighted delivery-feasibility packets.

---

## What GLTG Owns

GLTG owns:

```text
lead-time estimation
supplier lead-time comparison
P50 / P80 / P90 delivery bands
committable delivery dates
execution-path enumeration
single-source and parallel-split path options
critical-path and bottleneck reasoning in the engine layer
reforecasting after progress events
supplier-count edge-case handling
structured warnings and calculation traces
```

GLTG does not own:

```text
private supplier database persistence
RFQ/project workflow state
human approval workflow
IM/email account connectivity
final legal or commercial commitments
```

Consumers such as AIVAN, `giraffe-agent`, and `abcdYi` must call GLTG through the HTTP contract. They must not vendor or duplicate GLTG lead-time logic.

---

## Why GLTG Is Standalone

GLTG used to be duplicated inside multiple product repositories, which created conflicting local implementations and silent fallback behavior. The current architecture requires a single lead-time authority:

```text
AIVAN / giraffe-agent / abcdYi
        │
        │ HTTP contract only
        ▼
      GLTG
        │
        ├── deterministic graph engine
        ├── lead-time / path / reforecast API
        ├── CLI for local evaluation
        └── structured traces for auditability
```

No consumer should silently fall back to LLM-generated or local guessed lead-time calculations.

---

## Install

```bash
git clone https://github.com/GiraffeTechnology/GLTG.git
cd GLTG
python -m pip install -e ".[dev]"
```

For API-only runtime:

```bash
python -m pip install -e ".[api]"
```

With `uv`:

```bash
uv sync
```

---

## Run the API Service

```bash
uvicorn gltg.api.main:app --host 0.0.0.0 --port 8090
```

Health check:

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
| `GLTG_HOST` | `0.0.0.0` | Uvicorn bind host. |
| `GLTG_PORT` | `8090` | Uvicorn bind port. |

---

## HTTP API Contract

Default base URL:

```text
http://localhost:8090
```

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness: `{"status":"ok","service":"gltg"}`. |
| `GET` | `/version` | Service version and API version. |
| `POST` | `/v1/lead-time/estimate` | Estimate lead time, delivery dates, feasibility, selected supplier, warnings, and calculation trace. |
| `POST` | `/v1/paths/enumerate` | Return deterministic delivery path options, including single-source and parallel-split paths. |
| `POST` | `/v1/reforecast` | Apply progress-event deltas and return updated lead-time forecast. |

The `/v1` DTOs are intentionally simpler than the internal graph-engine domain models. The service layer maps transport input into the deterministic engine and returns stable JSON for consumers.

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

Response fields include:

```text
estimated_lead_time_days
earliest_delivery_date
most_likely_date
committable_date
risk_adjusted_date
p50_days
p80_days
p90_days
on_time_probability
feasibility
risk_level
warnings
calculation_trace
```

Consumers must store the GLTG response trace in decision packets or execution logs.

---

## Path Enumeration Example

```bash
curl -s http://localhost:8090/v1/paths/enumerate \
  -H 'content-type: application/json' \
  -d '{
    "order": {"product_type": "apparel", "quantity": 10000, "evaluation_date": "2026-06-30"},
    "suppliers": [
      {"supplier_id": "M1", "capacity_per_day": 800, "material_ready_days": 5, "production_days": 14, "qc_days": 2, "logistics_days": 7, "confidence": 0.8},
      {"supplier_id": "M2", "capacity_per_day": 600, "material_ready_days": 4, "production_days": 18, "qc_days": 3, "logistics_days": 8, "confidence": 0.7}
    ],
    "constraints": {"allow_partial_suppliers": true}
  }'
```

Returned paths are ranked deterministically by feasibility, lead time, confidence, and path ID.

Path modes:

```text
SINGLE_SOURCE
PARALLEL_SPLIT
```

---

## Reforecast Example

```bash
curl -s http://localhost:8090/v1/reforecast \
  -H 'content-type: application/json' \
  -d '{
    "order": {"product_type": "apparel", "quantity": 10000, "evaluation_date": "2026-06-30"},
    "suppliers": [
      {"supplier_id": "M1", "capacity_per_day": 800, "material_ready_days": 5, "production_days": 14, "qc_days": 2, "logistics_days": 7, "confidence": 0.8}
    ],
    "events": [
      {"supplier_id": "M1", "production_days_delta": 3, "note": "Factory queue delay"}
    ],
    "constraints": {"allow_partial_suppliers": true}
  }'
```

Progress events are additive deltas. Positive values delay the plan; negative values pull in the plan.

---

## Supplier-Count Edge Cases

GLTG must never crash or invent suppliers to fill three slots.

HTTP API behavior:

| Supplier count | Result |
|---:|---|
| `0` | `feasible=false`, empty path list, structured `NO_SUPPLIERS` warning. |
| `1` | Calculation proceeds with `LIMITED_COMPARISON` / single-source warning. |
| `2` | Calculation proceeds with `LIMITED_SUPPLIER_POOL` warning. |
| `3+` | Full comparison and path enumeration. |

Internal engine packet examples also surface limited-competition risk flags for fewer-than-three supplier cases.

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

## CLI Usage

Evaluate an order:

```bash
gltg evaluate examples/10000_shirts_order.json --summary
```

Write a feasibility packet:

```bash
gltg evaluate examples/10000_shirts_order.json --output packet.json
```

Reforecast an existing packet with progress events:

```bash
gltg reforecast packet.json examples/10000_shirts_progress_events.json --summary
```

Important: CLI `reforecast` expects an existing serialized packet as the first argument, not the original order JSON.

Edge-case examples:

```bash
gltg evaluate examples/zero_suppliers.json --summary
gltg evaluate examples/one_supplier.json --summary
gltg evaluate examples/two_suppliers.json --summary
```

---

## Example Files

| File | Description |
|---|---|
| `examples/10000_shirts_order.json` | 10,000-piece apparel order with participants, supplier memory, supplier responses, calendar, and dynamic form fields. |
| `examples/10000_shirts_participants.json` | Standalone participant profiles from the main shirt example. |
| `examples/10000_shirts_supplier_memory.json` | Supplier memory records used for duration adjustment. |
| `examples/10000_shirts_progress_events.json` | Progress events for reforecast testing. |
| `examples/zero_suppliers.json` | No supplier / no participant case. |
| `examples/one_supplier.json` | Single-supplier case. |
| `examples/two_suppliers.json` | Two-supplier case. |

---

## Tests and Acceptance Scripts

Run all tests:

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

Typical pre-release check:

```bash
pytest
python scripts/verify_gltg_5x.py
python scripts/run_api_edge_cases.py
python scripts/run_zero_one_two_supplier_cases.py
python scripts/run_10000_shirts_acceptance.py
```

Acceptance requirements:

1. Standalone install works.
2. API service exposes `/health`, `/version`, `/v1/lead-time/estimate`, `/v1/paths/enumerate`, and `/v1/reforecast`.
3. 0/1/2/3+ supplier cases do not crash.
4. Lead-time, path, and reforecast logic lives in GLTG, not in consumer repositories.
5. Outputs include structured warnings and calculation traces.
6. Human review remains required before downstream commercial commitments.

---

## Integration Contract for AIVAN / giraffe-agent / abcdYi

Consumers configure:

```bash
GLTG_API_BASE_URL=http://localhost:8090
GLTG_API_TIMEOUT_SECONDS=30
```

Consumer clients should:

```text
validate request shape
send JSON to GLTG with explicit timeout
return structured result: ok / data / error / status_code
persist GLTG response trace in decision packets or execution logs
avoid local fallback calculation
avoid LLM-generated lead-time replacement
surface GLTG errors to the caller clearly
```

GLTG is the calculation authority. Consumers may explain GLTG outputs, but they must not replace them.

---

## Why GLTG Is Not a Simple Calculator

A simple calculator adds stage durations. GLTG uses a graph model and evidence hierarchy.

GLTG can:

```text
build apparel workflow dependency graphs
resolve node schedules with calendar constraints
weight estimates by evidence quality
enumerate feasible delivery paths
prune infeasible paths with explanatory traces
identify bottlenecks and critical paths
compute p50 / p80 / p90 planning bands
produce single-source and split-delivery options
reforecast after progress events
return structured warnings for missing or weak evidence
```

Supplier-stated dates are evidence, not truth. GLTG also considers capability, capacity, historical memory, category baselines, actual progress events, calendar constraints, and missing evidence.

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

1. Calendar support uses simple working-day arithmetic. Complex multi-region holiday calendars are not yet supported.
2. On-time probability uses a normal-distribution approximation over p50/p80/p90 quantiles.
3. Path enumeration generates options from participant combinations but does not yet support full mixed-factory graph branching.
4. Outputs require human review before commercial commitment.

---

## Next Iteration

1. Monte Carlo delivery probability simulation.
2. Multi-region calendar support with supplier timezone-aware scheduling.
3. Full mixed-factory graph branching with cost modeling.
4. Live webhook integration for real-time reforecast triggers.
5. Buyer-portal output adapter.

---

## License

See `LICENSE`.
