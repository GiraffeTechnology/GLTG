# DEFECT-01 — HTTP ↔ Engine schema mapping

**Task 1 / Step 1 deliverable.** Mapping between the stable HTTP transport DTOs
(`gltg.api.schemas`) and the engine domain input (`gltg.models.order.ApparelOrderInput`).
This is the contract the new `gltg.services.engine_adapter` implements.

## Decision recorded

The audit's confirmed decision is **Option A: wire HTTP → `LeadTimeGraphEngine`**.
Consequence (measured, commit `dc9cda9`): the reference request that the old
summed-stage layer reported as **28 days** evaluates to **~275 commitable days**
through the engine, because the engine expands the full 22-node apparel workflow
(fabric ordering ~21d, shipment ~21d, sampling, customs, rework buffer) that the
4-field `SupplierInput` never expressed. This is intentional under Option A — the
28-day sum omitted fabric procurement and sea freight entirely. All affected
tests and the CI smoke value are updated to engine-derived numbers.

The simple service layer (`lead_time_service`, `path_enumeration_service`,
`reforecast_service`) is **demoted to input-prep**: the adapter reuses its
`_maybe_apply_baselines`, `_capacity_adjusted_production_days`, `_effective_target`,
and `_apply_events` helpers so capacity-floor, destination/air-sea transit, and
requirement-level baseline synthesis still shape the **engine input**. The engine
remains the single source of truth for dates / critical path / options.

## `/v1/lead-time/estimate`

### `OrderInput` → `ApparelOrderInput`

| HTTP field | Engine field | Mapping |
|---|---|---|
| `product_type` | `product_type` | passthrough |
| `quantity` | `quantity` | passthrough (drives sewing baseline) |
| `target_delivery_date` | `requested_delivery_date` | via `_effective_target` |
| `deadline_days` | `requested_delivery_date` | `_effective_target` = anchor + deadline_days when no explicit target |
| `evaluation_date` | `evaluation_date` | passthrough; defaults to `date.today()` **at the HTTP layer** (keeps engine deterministic) |
| `destination` | `destination` | passthrough; also feeds logistics baseline during input-prep |
| `logistics_mode` | — | consumed during input-prep (`baseline_stage_days` transit table); no engine field |
| — | `order_id` | synthesized (`http-estimate-<supplier_id>`) — engine requires it |

### `SupplierInput` → participant + supplier responses

Each supplier becomes a **single-factory** `ApparelOrderInput` (evaluated
independently; the best feasible supplier is then selected — this preserves
correct per-supplier selection and side-steps DEFECT-02, which is fixed in Task 2).

Input-prep first normalizes the supplier: `_maybe_apply_baselines` (fills stages
when all are 0) and `_capacity_adjusted_production_days` (capacity floor). The
resulting **effective** stage durations are injected as `SupplierResponse`
(`confirmed_days`, evidence weight 0.85) onto the dominant workflow node:

| HTTP supplier field | Engine node (`SupplierResponse.node_type`) |
|---|---|
| `material_ready_days` | `FABRIC_ORDERING` |
| `production_days` (capacity-adjusted) | `SEWING` |
| `qc_days` | `FINAL_QC` |
| `logistics_days` | `SHIPMENT` |
| `capacity_per_day` | `ParticipantProfile.capacity_per_day` (stored; engine consumption is DEFECT-03 / Task 2) |
| `confidence` | tie-break only (engine confidence is evidence-derived) |
| `name` | `ParticipantProfile.name` |

The participant is a `GARMENT_FACTORY` with capabilities spanning the factory
node types (`CUTTING/SEWING/FINAL_QC/PACKING`) so `PathEnumerator` treats it as a
factory. Nodes the supplier did not quote keep their category baselines — this is
why the engine total exceeds the 4-stage sum.

**Ambiguities & conservative resolutions**

1. *4 stages → 22 nodes is lossy.* Resolved by mapping each stage to its single
   dominant node and letting the rest fall to baselines (explicit > implicit).
2. *Per-supplier vs single multi-factory order.* Chosen per-supplier evaluation so
   selection stays correct before DEFECT-02 is fixed.
3. *`confidence` semantics.* Engine derives confidence from evidence; HTTP
   `confidence` is kept only as a deterministic tie-break in selection.

### `ApparelOrderInput` packet → `LeadTimeEstimateResponse`

| Response field | Source |
|---|---|
| `estimated_lead_time_days` | `(packet.commitable_date − anchor).days` **(engine, not sum)** |
| `earliest_delivery_date` | `packet.earliest_feasible_date` |
| `feasible` | engine status ≠ `NO_FEASIBLE_OPTION` and commitable ≤ target (or no target) |
| `selected_supplier_id` | best supplier id |
| `supplier_count` | `len(suppliers)` |
| `p50_days` / `p80_days` / `p90_days` | `(earliest / most_likely / commitable − anchor).days` |
| `minimum_feasible_days` | `p50_days` |
| `risk_level` | engine feasibility → `low`/`medium`/`high` |
| `warnings` | `NO_SUPPLIERS`, `BELOW_MIN_SUPPLIER_COUNT`, `LIMITED_COMPARISON`, `LIMITED_SUPPLIER_POOL`, `TARGET_NOT_MET` (preserved) |
| `calculation_trace` | per-supplier `SupplierTrace` (effective stage breakdown + engine commitable lead days as `total_lead_time_days`) |
| **`most_likely_date`** *(new, additive)* | `packet.most_likely_date` |
| **`committable_date`** *(new, additive)* | `packet.commitable_date` |
| **`risk_adjusted_date`** *(new, additive)* | `packet.risk_adjusted_latest_date` |
| **`on_time_probability`** *(new, additive)* | `packet.on_time_probability` |
| **`feasibility`** *(new, additive)* | `packet.status.value` (engine `FeasibilityStatus`) |

New fields are additive and optional — existing consumers are unaffected by their
presence.

## `/v1/paths/enumerate`

One `SINGLE_SOURCE` `DeliveryPath` per supplier built from that supplier's own
engine packet (engine-derived dates — already more correct than the shared-date
engine enumerator). When `supplier_count ≥ 2` and `allow_partial_suppliers`, a
`PARALLEL_SPLIT` path is added from a combined participant (summed capacity, min
stage durations) evaluated through the engine. Ranked deterministically:
feasible-first, shortest commitable, highest confidence, `path_id`.

## `/v1/reforecast`

`_apply_events` applies additive per-stage deltas to deep-copied suppliers
(history never mutated), then the engine-backed `estimate` runs on baseline and
updated suppliers. `baseline_lead_time_days` / `updated_lead_time_days` are
engine commitable lead days; `delta_days` their difference. Deterministic (anchored
on `evaluation_date`); the engine's own `ReforecastEngine` (DEFECT-04) is not used
by the HTTP path.
