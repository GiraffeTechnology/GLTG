from __future__ import annotations

import pytest
from pydantic import ValidationError

from gltg.behavioral.schemas import GLTGQuantiles, GLTGSimulationRequestV2


@pytest.mark.parametrize(
    "values",
    [
        {"p50_days": -0.01, "p80_days": 1, "p90_days": 2},
        {"p50_days": 2, "p80_days": 1, "p90_days": 3},
        {"p50_days": 1, "p80_days": 3, "p90_days": 2},
    ],
)
def test_quantile_schema_rejects_negative_or_out_of_order(values: dict) -> None:
    with pytest.raises(ValidationError):
        GLTGQuantiles(**values)


@pytest.mark.parametrize("tenant", [None, "", "   "])
def test_request_schema_requires_non_blank_tenant(tenant: str | None) -> None:
    payload = {
        "request_id": "S1-SCHEMA",
        "order": {"quantity": 1},
    }
    if tenant is not None:
        payload["tenant_id"] = tenant
    with pytest.raises(ValidationError):
        GLTGSimulationRequestV2.model_validate(payload)
