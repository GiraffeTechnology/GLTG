"""Validate private-provider snapshots before projecting model input fields."""

from typing import Any

from pydantic import ValidationError

from ..behavioral.schemas import GLTGSimulationRequestV2, GLTGTradeProcessingFactors
from ..integrations.giraffe_db_client import (
    GiraffeDBAuthError,
    GiraffeDBMalformedResponse,
)


def apply_factor_snapshot(req: GLTGSimulationRequestV2, snapshot: dict[str, Any]) -> None:
    for key, expected in (("tenant_id", req.tenant_id), ("supplier_id", req.supplier.supplier_id)):
        if key in snapshot and snapshot[key] != expected:
            raise GiraffeDBAuthError("factor snapshot identity did not match authenticated context")
    features = snapshot.get("feature_json") or {}
    if not isinstance(features, dict):
        raise GiraffeDBMalformedResponse("factor snapshot features must be an object")
    nested = features.get("trade_processing_factors") or {}
    if not isinstance(nested, dict):
        raise GiraffeDBMalformedResponse("trade processing factors must be an object")
    candidate = {}
    for group, field in GLTGTradeProcessingFactors.model_fields.items():
        model = field.annotation
        group_values = nested.get(group, {})
        if not isinstance(group_values, dict):
            raise GiraffeDBMalformedResponse("factor group must be an object")
        values = {name: features[name] for name in model.model_fields if name in features}
        values.update(group_values)
        candidate[group] = values
    try:
        # Validate provider values even if a caller supplied an overriding fact.
        GLTGTradeProcessingFactors.model_validate(candidate)
        merged = req.trade_processing_factors.model_dump(mode="json")
        for group, values in candidate.items():
            current = getattr(req.trade_processing_factors, group)
            for name, value in values.items():
                if name not in current.model_fields_set or getattr(current, name) is None:
                    merged[group][name] = value
        req.trade_processing_factors = GLTGTradeProcessingFactors.model_validate(merged)
    except ValidationError:
        raise GiraffeDBMalformedResponse("factor snapshot contains invalid model values") from None
    req.behavior_features.supplier_snapshot_id = str(snapshot["snapshot_id"])
