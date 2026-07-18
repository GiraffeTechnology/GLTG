# Stage 3 — GLTG Logic Audit (read-only, pre-change)

Date: 2026-07-17. Baseline on the audited tree: `python -m pytest -q` →
**241 passed** (Python 3.11.15). This audit was committed before any Stage 3
implementation change.

## 1. What GLTG currently calculates

Two real calculation engines exist, plus one LLM projection path:

1. **v1 graph engine** (`gltg.engine.LeadTimeGraphEngine` via
   `services/engine_adapter.py`): builds a single-factory apparel workflow
   graph per supplier (fabric ordering → sewing → QC → shipment, with
   cutting/packing capabilities), computes earliest/most-likely/commitable
   dates via critical path + evidence weighting, applies capacity-adjusted
   production days, deterministic supplier selection, and 0/1/2-supplier
   warnings. Real, executable, deterministic.
2. **Deterministic behavioral simulator**
   (`behavioral/simulator.py`, `BehavioralLeadTimeSimulator`): baseline
   quantiles (historical distribution if provided, else requirement-derived
   baseline), behavior adjustments (response delay, quote completeness,
   revisions, upstream signal, load, buyer volatility/decision delay,
   historical error), trade-processing factor model (material, capacity
   queue, process complexity, logistics, customs, packaging, export prep),
   three quantile composers (trade-processing spread, pseudo-lognormal,
   deterministic fallback), monotonic repair, risk/confidence scoring, and
   per-adjustment explanations. Real and deterministic — **but demoted**: it
   is only reachable as "fallback" (`GLTG_EVALUATOR_MODE=fallback`) or on
   provider failure with `GLTG_ALLOW_RULE_FALLBACK=true`.
3. **LLM evaluator** (`gltg.evaluator.*`): the **default** v2 path
   (`DEFAULT_EVALUATOR_MODE="llm"`, `DEFAULT_PROVIDER="qwen"`,
   `default_base_url=https://dashscope.aliyuncs.com/compatible-mode/v1`).
   The model, not GLTG code, produces the quantiles; GLTG validates/repairs
   the returned packet (schema, quantile monotonicity, evidence-ref
   guardrails) and projects it into the v2 response.

## 2. Internal coherence findings

Verified sound in the deterministic simulator:

- **Quantile monotonicity**: `_repair_monotonic` enforces P50 ≤ P80 ≤ P90
  and P50 ≥ 0 on both baseline and final output.
- **No negative days**: components are computed from clipped [0,1] scores ×
  positive day constants; buffers only add.
- **Units**: all `*_days` fields are days; all risk scores are clipped to
  [0,1] via `_clip`; no percentage-as-days confusion found.
- **Probability sanity**: response-delay reason inference is a softmax
  (sums to 1); `MATERIAL_STATUS_RISK` values ∈ [0,1]; confidence clipped to
  [0,1].
- **Determinism**: no RNG anywhere in the simulator; run id is a SHA-1 of
  the canonicalized request → same input + same versions = same output,
  including the run id. No hidden mutable state (module singleton is
  stateless); no input-order dependence found (sorting is explicit).
- **Missing data**: `_nz`/`_first` defaults are explicit; missing baselines
  fall back to requirement-derived stage days; missing observation IDs and
  unconfigured persistence produce warnings.

Issues found (fixed or disclosed in Stage 3):

| # | Issue | Severity |
| --- | --- | --- |
| L1 | Default v2 path silently calls an **external LLM** (DashScope) for calculations — violates the canonical boundary; out of the box (no key/network) evaluation degrades to a manual-review stub. Empirically: default request → `EVALUATOR_UNAVAILABLE`, quantiles P50=1.0/P80=5.0/P90=8.0 placeholders | critical |
| L2 | The manual-review stub reports `evaluation_mode="llm"` / `model_provider="qwen"` although no model ran, and emits placeholder quantiles derived from `p50*1.25/1.5` — resembles invented values (disclosed only via warning) | high |
| L3 | `/v2/reforecast` **does not apply events**: `routes.reforecast_v2` evaluates the request unchanged and merely echoes `events` in `applied_events`; no previous-vs-new quantiles, no delta | high |
| L4 | v2 response lacks top-level `source_observation_ids` (only inside `explanation_json`), and `persistence` is a bare bool with no truthful status (`persisted/skipped/failed/unavailable`) | medium |
| L5 | Unexplained constants: baseline `p80 = p50*1.18`, `p90 = p50*1.35`, uncertainty weights (0.18/0.16/…), buffer multipliers (0.8/1.2/1.3) have no calibration provenance (`calibration_version="none"` is at least honest) | medium (documented, not "fixed" — no real calibration data exists) |
| L6 | `_confidence` ignores evidence presence: removing `source_observation_ids` does not reduce `risk.confidence_score` (it does reduce `quote_confidence_score`) | medium |
| L7 | Double-counting risk: with trade-processing factors, `production_days` includes `setup_days` **and** `subprocess_days`, while `preproduction_days` also includes `setup_days` and `subprocess_days` is exported separately; the central shift sums `capacity_queue_days + expected_rework_days + …` but **not** `production_days` (production enters via baseline `base_production_days` max()), so the setup double-count does not reach quantiles; `subprocess_days` alone is double-entered into `production_days` while also displayed as a component | low (display-level; quantile path not double-counted) |
| L8 | Behavior tier boundaries (1.2/2.0/3.0 response-delay ratio; 0.9/0.7/0.5 completeness) are unexplained but stable, versioned under `rule_version` and explained per adjustment | low |

## 3. Output-component inventory

The full machine-readable inventory (inputs, source, formula, units, bounds,
defaults, missing-data behavior, warning, explanation, tests) is in
`docs/stage3/gltg_rule_inventory.json`, covering: requirement confirmation,
supplier response, quote confirmation/completeness, material procurement,
production, QC, logistics (export prep, origin inland, departure wait, main
freight, import clearance, destination inland), buyer decision, risk buffer,
supplier load, response delay, revision counts, buyer volatility, buyer
decision delay, historical error, fallback supplier, deadline feasibility,
confidence score, and manual review.

## 4. Confidence vs risk semantics

`risk.deadline_risk_level` (low/medium/medium_high/high) is derived from the
selected quantile vs deadline plus accumulated risk points;
`risk.confidence_score` ∈ [0,1] is supplier confidence + sample-size bonus −
quantile-width penalty − behavior penalty. The two are computed
independently and are not conflated. `deadline_feasible` compares the
**selected confidence quantile** (`constraints.lead_time_confidence`,
default P80) against the deadline — consistent with
`selected_confidence_days`.

## 5. Verdict on "real engine vs README-level description"

GLTG contains a real, coherent, deterministic lead-time engine (v1 graph
engine + v2 behavioral simulator). However, in the shipped default
configuration the deterministic v2 model is bypassed in favor of an external
LLM that is typically unreachable, so the out-of-the-box v2 API returns
manual-review stubs rather than calculations. Stage 3 re-promotes the
deterministic engine to the default v2 path and makes LLM assistance
explicit opt-in (see `STAGE3_FINAL_VALIDATION.md`).
