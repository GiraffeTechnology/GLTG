"""GLTG-owned deterministic numerical contract helpers.

This module does not activate an HTTP route and does not mutate the v2 response.
It freezes the accepted quantile component profile and provides a projection for
the request *after* evidence resolution and immediately before evaluator entry.
The input digest is not a complete result, risk, or approval identity.
"""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import math
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..behavioral.schemas import GLTGQuantiles, GLTGSimulationRequestV2


QUANTILE_CONTRACT_VERSION = "gltg.quantile-json-number.v1"
NUMERIC_PROFILE_ID = "gltg.quantiles.duration.v1"
UNIT = "day"
DAY_BASIS = "UNSPECIFIED"
ACTUAL_INPUT_DOMAIN = "gltg.actual-deterministic-input.v1"
QUANTILE_DOCUMENT_FIELDS = frozenset(
    {
        "quantile_contract_version",
        "numeric_profile_id",
        "unit",
        "day_basis",
        "p50_days",
        "p80_days",
        "p90_days",
    }
)
POST_RESOLUTION_NUMERIC_INPUT_FIELDS = (
    "order",
    "supplier",
    "historical_baseline",
    "behavior_features",
    "trade_processing_factors",
    "source_observation_ids",
    "constraints",
)
class CanonicalizationError(ValueError):
    """Raised when a value cannot be represented by the RFC 8785 boundary."""


def _number(value: int | float) -> str:
    if isinstance(value, bool):
        raise CanonicalizationError("boolean is not a JSON number")
    if isinstance(value, int):
        try:
            binary64 = float(value)
        except OverflowError as exc:
            raise CanonicalizationError(
                "integer is not exactly representable as binary64"
            ) from exc
        if not math.isfinite(binary64) or int(binary64) != value:
            raise CanonicalizationError("integer is not exactly representable as binary64")
        return _number(binary64)
    if not math.isfinite(value):
        raise CanonicalizationError("non-finite JSON number")
    if value == 0:
        return "0"
    absolute = abs(value)
    decimal = Decimal(repr(value))
    if 1e-6 <= absolute < 1e21:
        rendered = format(decimal, "f").rstrip("0").rstrip(".")
        return rendered or "0"
    mantissa, exponent = format(decimal.normalize(), "e").split("e")
    mantissa = mantissa.rstrip("0").rstrip(".")
    exponent_number = int(exponent)
    sign = "+" if exponent_number >= 0 else ""
    return f"{mantissa}e{sign}{exponent_number}"


def _utf16_key(value: str) -> bytes:
    try:
        return value.encode("utf-16-be")
    except UnicodeEncodeError as exc:
        raise CanonicalizationError("unpaired surrogate in object key") from exc


def _canonical(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise CanonicalizationError("unpaired surrogate in string") from exc
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise CanonicalizationError("JSON object keys must be strings")
        items = sorted(value.items(), key=lambda item: _utf16_key(item[0]))
        return "{" + ",".join(
            f"{_canonical(key)}:{_canonical(item)}" for key, item in items
        ) + "}"
    raise CanonicalizationError(f"unsupported JSON value type: {type(value).__name__}")


def rfc8785_bytes(value: Any) -> bytes:
    """Return portable RFC 8785 UTF-8 bytes for an I-JSON-compatible value."""

    return _canonical(value).encode("utf-8")


class QuantileProfileDocument(BaseModel):
    """Closed seven-field quantile component document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quantile_contract_version: Literal["gltg.quantile-json-number.v1"] = (
        QUANTILE_CONTRACT_VERSION
    )
    numeric_profile_id: Literal["gltg.quantiles.duration.v1"] = NUMERIC_PROFILE_ID
    unit: Literal["day"] = UNIT
    day_basis: Literal["UNSPECIFIED"] = DAY_BASIS
    p50_days: float = Field(ge=0, allow_inf_nan=False)
    p80_days: float = Field(ge=0, allow_inf_nan=False)
    p90_days: float = Field(ge=0, allow_inf_nan=False)

    @field_validator("p50_days", "p80_days", "p90_days", mode="before")
    @classmethod
    def _reject_boolean(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("quantiles must be JSON numbers")
        if isinstance(value, int):
            try:
                _number(value)
            except CanonicalizationError as exc:
                raise ValueError(str(exc)) from exc
        return value

    @model_validator(mode="after")
    def _ordered(self) -> QuantileProfileDocument:
        if not self.p50_days <= self.p80_days <= self.p90_days:
            raise ValueError("quantiles must satisfy P50 <= P80 <= P90")
        return self


def build_quantile_document(
    quantiles: GLTGQuantiles | Mapping[str, Any],
) -> QuantileProfileDocument:
    """Build the closed component document without an embedded digest."""

    values = (
        quantiles.model_dump(mode="json")
        if isinstance(quantiles, GLTGQuantiles)
        else dict(quantiles)
    )
    return QuantileProfileDocument(
        p50_days=values["p50_days"],
        p80_days=values["p80_days"],
        p90_days=values["p90_days"],
    )


def quantile_canonical_sha256(
    document: QuantileProfileDocument | Mapping[str, Any],
) -> str:
    """Hash exactly the validated seven-field document; the digest is external."""

    validated = (
        document
        if isinstance(document, QuantileProfileDocument)
        else QuantileProfileDocument.model_validate(document)
    )
    canonical = rfc8785_bytes(validated.model_dump(mode="json"))
    return hashlib.sha256(canonical).hexdigest()


def project_post_resolution_numeric_input(req: GLTGSimulationRequestV2) -> dict[str, Any]:
    """Project the evidence-resolved request at the pre-evaluator boundary.

    Callers are responsible for invoking this only after ``resolve_evidence``
    has applied accepted private-data values/defaults and immediately before
    evaluator entry. Authorization, provider, display and operational metadata
    are deliberately excluded.
    """

    request_json = req.model_dump(mode="json")
    return {name: request_json[name] for name in POST_RESOLUTION_NUMERIC_INPUT_FIELDS}


def actual_input_snapshot_sha256(req: GLTGSimulationRequestV2) -> str:
    """Hash the post-resolution numerical input, not result/risk/approval state."""

    domain = f"{ACTUAL_INPUT_DOMAIN}\n".encode()
    projected = project_post_resolution_numeric_input(req)
    return hashlib.sha256(domain + rfc8785_bytes(projected)).hexdigest()


__all__ = [
    "ACTUAL_INPUT_DOMAIN",
    "DAY_BASIS",
    "NUMERIC_PROFILE_ID",
    "POST_RESOLUTION_NUMERIC_INPUT_FIELDS",
    "QUANTILE_CONTRACT_VERSION",
    "QUANTILE_DOCUMENT_FIELDS",
    "UNIT",
    "CanonicalizationError",
    "QuantileProfileDocument",
    "actual_input_snapshot_sha256",
    "build_quantile_document",
    "project_post_resolution_numeric_input",
    "quantile_canonical_sha256",
    "rfc8785_bytes",
]
