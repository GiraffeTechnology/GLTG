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

## Core Principle

All future development must:

1. Map to the PRD scope;
2. Have explicit Acceptance Criteria;
3. Move toward production-ready delivery;
4. Not use algorithmic complexity as a substitute for delivery.

---

## License

See `LICENSE`.
