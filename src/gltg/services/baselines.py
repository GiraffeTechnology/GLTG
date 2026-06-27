"""Deterministic baseline stage estimates for requirement-level inputs.

When a consumer cannot supply explicit per-stage durations (e.g. an early-stage
RFQ that only knows quantity + destination), GLTG synthesizes stage estimates
from apparel category defaults plus destination/logistics transit. This keeps
all lead-time math in GLTG -- consumers never compute stages themselves.

Ported from the lead-time logic that previously lived inside aivan so the
standalone service remains the single source of truth.
"""

from __future__ import annotations

import math

# Default (non-production) apparel stages, in days.
APPAREL_MATERIAL_READY_DAYS = (
    1  # requirement clarification
    + 2  # supplier response SLA
    + 7  # material procurement
    + 7  # sample + approval
)
APPAREL_QC_DAYS = 1 + 2  # inline QC + final QC
APPAREL_FINISHING_PACKING_DAYS = 2 + 1  # finishing + packaging
DEFAULT_DAILY_CAPACITY = 500
PRODUCTION_EFFICIENCY = 0.85
RISK_BUFFER_DAYS = 5

# Logistics legs bundled into the logistics stage (domestic + customs + import + final mile).
LOGISTICS_OVERHEAD_DAYS = 2 + 3 + 3 + 2

SEA_TRANSIT_DAYS = {
    "vancouver": 18,
    "los angeles": 14,
    "new york": 28,
    "london": 25,
    "rotterdam": 22,
}
AIR_TRANSIT_DAYS = {
    "vancouver": 3,
    "los angeles": 2,
    "new york": 3,
    "london": 2,
    "rotterdam": 2,
}


def transit_days(destination: str | None, logistics_mode: str | None) -> int:
    dest = (destination or "").lower()
    if "air" in (logistics_mode or "").lower():
        for city, days in AIR_TRANSIT_DAYS.items():
            if city in dest:
                return days
        return 4
    for city, days in SEA_TRANSIT_DAYS.items():
        if city in dest:
            return days
    return 20


def production_days(quantity: int, capacity_per_day: int | None) -> float:
    cap = capacity_per_day or DEFAULT_DAILY_CAPACITY
    effective = max(int(cap * PRODUCTION_EFFICIENCY), 1)
    return float(max(math.ceil(quantity / effective), 1) + 2)


def baseline_stage_days(
    quantity: int,
    destination: str | None,
    logistics_mode: str | None,
    capacity_per_day: int | None,
) -> dict[str, float]:
    """Return synthesized stage durations for a requirement with no supplier data."""
    return {
        "material_ready_days": float(APPAREL_MATERIAL_READY_DAYS),
        "production_days": production_days(quantity, capacity_per_day),
        "qc_days": float(APPAREL_QC_DAYS + APPAREL_FINISHING_PACKING_DAYS),
        "logistics_days": float(
            LOGISTICS_OVERHEAD_DAYS + transit_days(destination, logistics_mode)
        ),
    }
