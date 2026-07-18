"""v2 request pipeline: evidence resolution → evaluation → persistence.

Keeps the HTTP routes thin and owns the three Stage 3 behaviors:

1. **Evidence resolution** — when ``request.evidence.use_giraffe_db`` is true,
   retrieve the supplier record and behavior summary from giraffe-db under the
   request tenant. Failures are explicit (typed warnings or a 503-mapped
   ``DB_UNAVAILABLE`` error); evidence is never fabricated.
2. **Reforecast event application** — map typed events onto request fields so
   ``/v2/reforecast`` actually recomputes with new evidence and discloses
   previous quantiles, deltas, and changed components.
3. **Persistence** — optionally persist the run to giraffe-db
   (``GLTG_PERSIST_RUNS=true``) with a truthful outcome status.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from ..behavioral.schemas import (
    GLTGPersistenceRef,
    GLTGQuantiles,
    GLTGReforecastDeltaV2,
    GLTGReforecastRequestV2,
    GLTGReforecastResponseV2,
    GLTGSimulationRequestV2,
    GLTGSimulationResponseV2,
    GLTGWarningV2,
)
from ..errors import GLTGError
from ..evaluator import orchestrator as gltg_evaluator
from ..integrations.giraffe_db_client import (
    GiraffeDBAuthError,
    GiraffeDBClient,
    GiraffeDBError,
    GiraffeDBMalformedResponse,
    GiraffeDBNotFound,
    GiraffeDBUnavailable,
    client_from_env,
)


class EvidenceUnavailableError(GLTGError):
    """giraffe-db was required but unreachable; mapped to HTTP 503."""


class EvidenceAuthError(GLTGError):
    """giraffe-db rejected our service auth or tenant; fail closed."""


def _warn(code: str, severity: str, message: str) -> GLTGWarningV2:
    return GLTGWarningV2(code=code, severity=severity, message=message)


# --------------------------------------------------------------------------- #
# Evidence resolution
# --------------------------------------------------------------------------- #
# Bounded confidence penalties for requested-but-unusable evidence. The total
# applied penalty is capped so degraded evidence can never zero out an
# otherwise healthy confidence score on its own.
BEHAVIOR_EVIDENCE_PENALTY = 0.1
MAX_EVIDENCE_CONFIDENCE_PENALTY = 0.2


class ResolvedEvidence:
    def __init__(self) -> None:
        self.warnings: list[GLTGWarningV2] = []
        self.explanation: dict[str, Any] = {}
        self.extra_observation_ids: list[str] = []
        self.confidence_penalty: float = 0.0
        self.force_manual_review: bool = False


def resolve_evidence(
    req: GLTGSimulationRequestV2, client: GiraffeDBClient | None
) -> ResolvedEvidence:
    """Fetch giraffe-db evidence for the request (mutates req fields that are
    unset, never overwriting caller-supplied values)."""

    resolved = ResolvedEvidence()
    if not req.evidence.use_giraffe_db:
        return resolved

    meta: dict[str, Any] = {
        "source": "giraffe-db",
        "tenant_id": req.tenant_id,
        "supplier_id": req.supplier.supplier_id,
        "retrieved": [],
        "status": "ok",
    }
    resolved.explanation["evidence"] = meta

    if client is None:
        raise EvidenceUnavailableError(
            "evidence.use_giraffe_db=true but GLTG_GIRAFFE_DB_BASE_URL is not configured"
        )
    if not req.supplier.supplier_id:
        raise GLTGError("evidence.use_giraffe_db=true requires supplier.supplier_id")

    supplier_id = req.supplier.supplier_id

    # Supplier record — auth and availability failures fail closed.
    try:
        record = client.get_supplier(supplier_id, req.tenant_id)
    except GiraffeDBAuthError as exc:
        raise EvidenceAuthError(str(exc)) from exc
    except GiraffeDBUnavailable as exc:
        raise EvidenceUnavailableError(str(exc)) from exc
    except GiraffeDBNotFound:
        meta["status"] = "supplier_not_found"
        resolved.force_manual_review = True
        resolved.confidence_penalty += 0.1
        resolved.warnings.append(_warn(
            "EVIDENCE_NOT_FOUND",
            "high",
            f"giraffe-db has no supplier {supplier_id} for tenant {req.tenant_id}; "
            "no evidence was substituted.",
        ))
        return resolved
    except GiraffeDBMalformedResponse as exc:
        raise GLTGError(f"EVIDENCE_MALFORMED: {exc}") from exc

    meta["retrieved"].append("supplier_record")
    if not req.supplier.name:
        req.supplier.name = record.get("name_en") or record.get("supplier_name")
    if record.get("is_synthetic") is True:
        resolved.warnings.append(_warn(
            "SYNTHETIC_EVIDENCE",
            "low",
            "Supplier evidence is synthetic (is_synthetic=true); outputs must not "
            "be represented as real transaction history.",
        ))
    if record.get("active") is False:
        resolved.force_manual_review = True
        resolved.warnings.append(_warn(
            "SUPPLIER_INACTIVE",
            "high",
            "giraffe-db marks this supplier inactive.",
        ))
    meta["supplier_is_synthetic"] = record.get("is_synthetic")

    # Behavior summary. Auth failures still fail closed; every other way the
    # behavior evidence can be unusable (endpoint 404, malformed payload,
    # missing required fields, empty summary, or the endpoint being
    # unreachable while the supplier read succeeded) degrades explicitly:
    # stable warning code, a bounded confidence penalty, and a
    # machine-readable status — never invented behavior values.
    summary: dict[str, Any] | None = None
    behavior_status = "ok"
    try:
        summary = client.get_supplier_behavior_summary(supplier_id, req.tenant_id)
    except GiraffeDBAuthError as exc:
        raise EvidenceAuthError(str(exc)) from exc
    except GiraffeDBUnavailable:
        behavior_status = "endpoint_unavailable"
    except GiraffeDBNotFound:
        behavior_status = "endpoint_not_found"
    except GiraffeDBMalformedResponse:
        behavior_status = "malformed_payload"

    if summary is not None and not isinstance(summary.get("observation_count"), (int, float)):
        # Required field missing/invalid: the payload cannot be trusted.
        behavior_status = "malformed_payload"
        summary = None

    if summary is not None:
        meta["retrieved"].append("behavior_summary")
        observation_count = int(summary.get("observation_count") or 0)
        meta["behavior_observation_count"] = observation_count
        snapshot = summary.get("latest_snapshot") or None
        if snapshot and snapshot.get("snapshot_id"):
            resolved.extra_observation_ids.append(str(snapshot["snapshot_id"]))
            features = snapshot.get("feature_json") or {}
            supplier_features = req.behavior_features.supplier
            for source_key, target_attr in (
                ("response_delay_ratio", "response_delay_ratio"),
                ("quote_completeness_score", "quote_completeness_score"),
                ("historical_on_time_delivery_rate", "historical_on_time_delivery_rate"),
            ):
                if getattr(supplier_features, target_attr, None) is None and isinstance(
                    features.get(source_key), (int, float)
                ):
                    setattr(supplier_features, target_attr, float(features[source_key]))
        delay = summary.get("response_delay") or {}
        if (
            req.behavior_features.supplier.response_delay_ratio is None
            and isinstance(delay.get("response_delay_ratio"), (int, float))
        ):
            req.behavior_features.supplier.response_delay_ratio = float(
                delay["response_delay_ratio"]
            )
        if observation_count == 0:
            behavior_status = "no_observations"

    meta["behavior_evidence_status"] = behavior_status
    if behavior_status != "ok":
        resolved.confidence_penalty += BEHAVIOR_EVIDENCE_PENALTY
        resolved.warnings.append(_warn(
            "MISSING_BEHAVIOR_EVIDENCE",
            "medium",
            f"Behavior evidence unusable ({behavior_status}); "
            "confidence reduced, no behavior invented.",
        ))

    if resolved.extra_observation_ids:
        merged = list(req.source_observation_ids)
        for observation_id in resolved.extra_observation_ids:
            if observation_id not in merged:
                merged.append(observation_id)
        req.source_observation_ids = merged
    return resolved


def _apply_evidence_to_response(
    response: GLTGSimulationResponseV2, resolved: ResolvedEvidence
) -> None:
    response.warnings.extend(resolved.warnings)
    if resolved.explanation:
        response.explanation_json.update(resolved.explanation)
    if resolved.confidence_penalty and response.risk.confidence_score is not None:
        penalty = round(min(resolved.confidence_penalty, MAX_EVIDENCE_CONFIDENCE_PENALTY), 3)
        adjusted = max(0.0, round(response.risk.confidence_score - penalty, 3))
        reason = (
            resolved.explanation.get("evidence", {}).get("behavior_evidence_status")
            or resolved.explanation.get("evidence", {}).get("status")
            or "missing_evidence"
        )
        response.explanation_json.setdefault("adjustments", []).append({
            "feature": "missing_evidence",
            "value": penalty,
            "adjustment": f"-{penalty} confidence_score",
            "reason": f"Requested giraffe-db evidence was unusable ({reason}); confidence reduced.",
        })
        response.risk.confidence_score = adjusted
    if resolved.force_manual_review:
        response.risk.manual_review_required = True
        response.manual_review_required = True


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def _persist_enabled() -> bool:
    return os.environ.get("GLTG_PERSIST_RUNS", "").strip().lower() in {"1", "true", "yes", "on"}


def _request_fingerprint(req: GLTGSimulationRequestV2) -> str:
    """SHA-1 over the canonical JSON of the request that was actually evaluated."""
    canonical = json.dumps(
        req.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def persist_run(
    req: GLTGSimulationRequestV2,
    response: GLTGSimulationResponseV2,
    client: GiraffeDBClient | None,
    *,
    reforecast_meta: dict[str, Any] | None = None,
) -> None:
    """Attach a truthful persistence outcome to the response.

    ``req`` must be the request the response was actually computed from —
    for reforecasts that is the *updated* request (events applied), so the
    persisted inputs reproduce the persisted output.
    """

    if not _persist_enabled():
        response.persistence = GLTGPersistenceRef(
            status="unavailable" if client is None else "skipped",
            detail="giraffe-db persistence disabled (GLTG_PERSIST_RUNS not set)",
        )
        return
    if client is None:
        response.persistence = GLTGPersistenceRef(
            status="unavailable",
            detail="GLTG_PERSIST_RUNS=true but GLTG_GIRAFFE_DB_BASE_URL is not configured",
        )
        response.warnings.append(_warn(
            "PERSISTENCE_NOT_CONFIGURED",
            "medium",
            "Run persistence requested but giraffe-db is not configured.",
        ))
        return

    components = response.components
    supplier_id = req.supplier.supplier_id
    payload: dict[str, Any] = {
        # PK is assigned by giraffe-db in canonical form; GLTG's internal
        # deterministic run id travels inside output_json.
        "procurement_case_id": req.case_context.procurement_case_id,
        "rfq_id": req.case_context.rfq_id,
        "quote_id": req.case_context.quote_id,
        "supplier_id": supplier_id,
        "base_input_json": {
            "gltg_internal_run_id": response.gltg_run_id,
            "request_id": req.request_id,
            "order": req.order.model_dump(mode="json"),
            "constraints": req.constraints.model_dump(mode="json"),
            "model_version": response.model_version,
            "rule_version": response.rule_version,
            "calibration_version": response.calibration_version,
            # Replay guarantee: the complete evaluated request and its
            # fingerprint (for reforecasts this is the updated request).
            "request_json": req.model_dump(mode="json"),
            "input_fingerprint": _request_fingerprint(req),
            **({"reforecast_meta": reforecast_meta} if reforecast_meta else {}),
        },
        "behavior_input_json": req.behavior_features.model_dump(mode="json", exclude_none=True),
        "output_json": {
            "quantiles": response.quantiles.model_dump(mode="json"),
            "risk": response.risk.model_dump(mode="json"),
            "warnings": [w.model_dump(mode="json") for w in response.warnings],
            "source_observation_ids": response.source_observation_ids,
            "evaluation_mode": response.evaluation_mode,
        },
        "base_production_days": components.base_production_days,
        "base_procurement_days": components.base_procurement_days,
        "supplier_response_buffer_days": components.supplier_response_buffer_days,
        "supplier_uncertainty_buffer_days": components.supplier_uncertainty_buffer_days,
        "buyer_decision_buffer_days": components.buyer_decision_buffer_days,
        "logistics_buffer_days": components.logistics_buffer_days,
        "risk_buffer_days": components.risk_buffer_days,
        "final_p50_days": response.quantiles.p50_days,
        "final_p80_days": response.quantiles.p80_days,
        "final_p90_days": response.quantiles.p90_days,
        "deadline_risk_level": response.risk.deadline_risk_level,
        "explanation_json": response.explanation_json or {"summary": "gltg run"},
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    try:
        stored = client.persist_gltg_run(payload, req.tenant_id)
    except GiraffeDBError as exc:
        response.persistence = GLTGPersistenceRef(
            status="failed", detail=f"{exc.code}: {exc}"
        )
        response.warnings.append(_warn(
            "PERSISTENCE_FAILED",
            "medium",
            f"giraffe-db run persistence failed ({exc.code}); result returned without a stored run.",
        ))
        return
    response.persistence = GLTGPersistenceRef(
        status="persisted",
        persisted_to_giraffe_db=True,
        giraffe_db_run_id=str(stored["gltg_run_id"]),
    )


# --------------------------------------------------------------------------- #
# Reforecast event application
# --------------------------------------------------------------------------- #
def _apply_event(req: GLTGSimulationRequestV2, event: dict[str, Any]) -> bool:
    """Apply one typed event to the request. Returns False for unknown types."""

    event_type = str(event.get("event_type", ""))
    factors = req.trade_processing_factors
    if event_type == "supplier_response_delay":
        ratio = event.get("response_delay_ratio")
        if isinstance(ratio, (int, float)):
            factors.behavior.supplier_response_delay_ratio = float(ratio)
            req.behavior_features.supplier.response_delay_ratio = float(ratio)
            return True
        return False
    if event_type == "material_availability_change":
        status = event.get("material_availability_status")
        if isinstance(status, str) and status:
            factors.material.material_availability_status = status
            if isinstance(event.get("raw_material_lead_time_estimate_days"), (int, float)):
                factors.material.raw_material_lead_time_estimate_days = float(
                    event["raw_material_lead_time_estimate_days"]
                )
            return True
        return False
    if event_type == "capacity_update":
        applied = False
        for key in ("capacity_utilization_ratio", "nominal_daily_capacity", "effective_daily_capacity"):
            if isinstance(event.get(key), (int, float)):
                setattr(factors.supplier_execution, key, float(event[key]))
                applied = True
        return applied
    if event_type == "buyer_requirement_revision":
        applied = False
        if isinstance(event.get("requirement_volatility_score"), (int, float)):
            factors.requirement.requirement_volatility_score = float(
                event["requirement_volatility_score"]
            )
            applied = True
        if isinstance(event.get("requirement_change_count"), int):
            req.behavior_features.buyer.requirement_change_count = event["requirement_change_count"]
            applied = True
        return applied
    if event_type == "logistics_disruption":
        applied = False
        for key in ("logistics_disruption_score", "freight_space_risk", "route_baseline_days"):
            if isinstance(event.get(key), (int, float)):
                setattr(factors.logistics_trade, key, float(event[key]))
                applied = True
        return applied
    if event_type == "qc_delay":
        applied = False
        for key in ("qc_intensity_score", "rework_probability", "rework_days_if_triggered"):
            if isinstance(event.get(key), (int, float)):
                setattr(factors.processing, key, float(event[key]))
                applied = True
        return applied
    if event_type == "improved_evidence":
        ids = event.get("source_observation_ids")
        if isinstance(ids, list) and ids:
            merged = list(req.source_observation_ids)
            for observation_id in ids:
                if str(observation_id) not in merged:
                    merged.append(str(observation_id))
            req.source_observation_ids = merged
            return True
        return False
    return False


# --------------------------------------------------------------------------- #
# Public pipeline entry points
# --------------------------------------------------------------------------- #
def run_simulation(
    req: GLTGSimulationRequestV2, *, persist: bool = True
) -> GLTGSimulationResponseV2:
    client = client_from_env()
    resolved = resolve_evidence(req, client)
    response = gltg_evaluator.evaluate(req)
    _apply_evidence_to_response(response, resolved)
    if persist:
        persist_run(req, response, client)
    return response


def run_reforecast(req: GLTGReforecastRequestV2) -> GLTGReforecastResponseV2:
    client = client_from_env()

    base_req = GLTGSimulationRequestV2.model_validate(
        req.model_dump(mode="json", exclude={"events"})
    )
    resolved = resolve_evidence(base_req, client)
    previous = gltg_evaluator.evaluate(base_req)
    _apply_evidence_to_response(previous, resolved)

    updated_req = GLTGSimulationRequestV2.model_validate(
        base_req.model_dump(mode="json")
    )
    applied: list[dict[str, Any]] = []
    unapplied: list[dict[str, Any]] = []
    for event in req.events:
        (applied if _apply_event(updated_req, event) else unapplied).append(event)

    updated = gltg_evaluator.evaluate(updated_req)
    # Evidence context and penalties apply equally to the updated run.
    _apply_evidence_to_response(updated, resolved)

    changed_components: dict[str, float] = {}
    for field_name, new_value in updated.components.model_dump().items():
        old_value = getattr(previous.components, field_name)
        if round(new_value - old_value, 2) != 0:
            changed_components[field_name] = round(new_value - old_value, 2)

    triggering: list[str] = []
    for event in applied:
        for observation_id in event.get("source_observation_ids", []) or []:
            if str(observation_id) not in triggering:
                triggering.append(str(observation_id))

    response = GLTGReforecastResponseV2(
        **updated.model_dump(mode="json"),
        applied_events=applied,
        unapplied_events=unapplied,
        previous_quantiles=GLTGQuantiles(**previous.quantiles.model_dump()),
        delta=GLTGReforecastDeltaV2(
            p50_days=round(updated.quantiles.p50_days - previous.quantiles.p50_days, 2),
            p80_days=round(updated.quantiles.p80_days - previous.quantiles.p80_days, 2),
            p90_days=round(updated.quantiles.p90_days - previous.quantiles.p90_days, 2),
        ),
        changed_components=changed_components,
        triggering_observation_ids=triggering,
    )
    if unapplied:
        response.warnings.append(_warn(
            "UNAPPLIED_REFORECAST_EVENT",
            "medium",
            f"{len(unapplied)} event(s) had unknown types or missing fields and were not applied.",
        ))
    response.explanation_json["reforecast"] = {
        "previous_quantiles": previous.quantiles.model_dump(),
        "applied_event_types": [str(event.get("event_type", "")) for event in applied],
        "changed_components": changed_components,
    }
    # Persist the UPDATED request (events applied) so the stored inputs
    # reproduce the stored output; keep the event audit trail alongside.
    persist_run(
        updated_req,
        response,
        client,
        reforecast_meta={
            "reforecast": True,
            "applied_events": applied,
            "unapplied_events": unapplied,
            "triggering_observation_ids": triggering,
            "previous_run_id": previous.gltg_run_id,
        },
    )
    return response


__all__ = [
    "EvidenceAuthError",
    "EvidenceUnavailableError",
    "run_reforecast",
    "run_simulation",
]
