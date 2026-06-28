"""Participant and supplier models."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from .enums import ApparelNodeType, ParticipantType
from .capability import Capability

if TYPE_CHECKING:
    pass


class SupplierStateOverride(BaseModel):
    """Real-time supplier-state signal applied on top of historical baselines.

    Sourced upstream by aivan's supplier-signal layer; GLTG treats every field as
    a given input and never recomputes it. All defaults are no-ops so an order
    carrying no override schedules and ranks identically to the pre-signal engine
    (regression guard -- see ``test_no_override_produces_identical_result``).
    """

    # Active signals (LLM-extracted upstream).
    available_capacity_per_day: int | None = None  # overrides historical capacity for production
    earliest_available_date: date | None = None     # supplier cannot start this order before here
    # Lead-time multiplier for the supplier's non-production stages (1.0 = no change).
    load_factor: float = 1.0
    # Passive behaviour signals; drive the ranking tiebreak penalty (0.0-1.0).
    response_speed_score: float = 1.0
    completeness_score: float = 1.0
    # Opaque markers surfaced to the buyer; never alter the date/score math.
    risk_flags: list[str] = []


class ParticipantProfile(BaseModel):
    """A supply-chain participant (factory, supplier, logistics provider, etc.)."""

    participant_id: str
    name: str
    participant_type: ParticipantType
    capabilities: list[Capability] = []
    location: str | None = None
    capacity_per_day: int | None = None    # units per working day (aggregate)
    moq: int | None = None                 # minimum order quantity
    available_from: date | None = None
    reliability_score: float | None = None   # 0.0-1.0
    quality_score: float | None = None       # 0.0-1.0
    on_time_delivery_rate: float | None = None  # 0.0-1.0
    # Optional real-time state signal; absent -> pure historical baseline behaviour.
    state_override: SupplierStateOverride | None = None
    metadata: dict[str, Any] = {}

    def can_handle(self, node_type: ApparelNodeType) -> bool:
        """Return True if any capability covers node_type."""
        return any(c.node_type == node_type for c in self.capabilities)

    def get_capability(self, node_type: ApparelNodeType) -> Capability | None:
        """Return the first matching capability, or None."""
        for c in self.capabilities:
            if c.node_type == node_type:
                return c
        return None


class SupplierMemoryRecord(BaseModel):
    """A historical performance record for a participant on a specific task."""

    record_id: str
    participant_id: str
    node_type: ApparelNodeType | None = None
    order_quantity: int | None = None
    stated_days: float | None = None   # what supplier said
    actual_days: float | None = None   # what actually happened
    on_time: bool | None = None
    quality_pass: bool | None = None
    notes: str | None = None
    recorded_at: date | None = None


class SupplierResponse(BaseModel):
    """A formal quote or confirmation from a supplier for a specific node."""

    response_id: str
    participant_id: str
    node_type: ApparelNodeType | None = None
    confirmed_days: float | None = None
    earliest_start: date | None = None
    price_indication: float | None = None
    currency: str = "USD"
    conditions: str | None = None
    confirmed_at: date | None = None
    expires_at: date | None = None
