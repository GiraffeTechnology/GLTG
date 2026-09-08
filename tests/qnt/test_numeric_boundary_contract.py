from __future__ import annotations

import copy
import hashlib
import importlib
import math

import pytest
from pydantic import ValidationError

from gltg.behavioral.schemas import GLTGQuantiles, GLTGSimulationRequestV2
from gltg.contracts.numeric_boundary import (
    ACTUAL_INPUT_DOMAIN,
    DAY_BASIS,
    NUMERIC_PROFILE_ID,
    POST_RESOLUTION_NUMERIC_INPUT_FIELDS,
    QUANTILE_CONTRACT_VERSION,
    QUANTILE_DOCUMENT_FIELDS,
    UNIT,
    CanonicalizationError,
    QuantileProfileDocument,
    actual_input_snapshot_sha256,
    build_quantile_document,
    project_post_resolution_numeric_input,
    quantile_canonical_sha256,
    rfc8785_bytes,
)
from gltg.evaluator import evaluate
from gltg.services.v2_pipeline import (
    ResolvedEvidence,
    _apply_evidence_to_response,
    resolve_evidence,
)


PRIMARY_CANONICAL = (
    b'{"day_basis":"UNSPECIFIED","numeric_profile_id":"gltg.quantiles.duration.v1",'
    b'"p50_days":58,"p80_days":68.44,"p90_days":78.3,'
    b'"quantile_contract_version":"gltg.quantile-json-number.v1","unit":"day"}'
)
PRIMARY_SHA256 = "18a329bfddb0122ac4d790ccd91d4663ed93f2c8a7b9e265906a07d24928a267"


def _request() -> GLTGSimulationRequestV2:
    return GLTGSimulationRequestV2.model_validate(
        {
            "request_id": "QNT_LOCAL_GREEN_001",
            "tenant_id": "tenant_qnt_green",
            "source_system": "qnt-test",
            "source_trace_id": "trace-a",
            "order": {"quantity": 10000, "deadline_days": 1000},
            "supplier": {
                "supplier_id": "requirement",
                "capacity_per_day": 500,
                "supplier_stated_lead_time_days": 28,
                "confidence": 0.7,
            },
            "historical_baseline": {
                "baseline_source": "QNT_SYNTHETIC_V1",
                "sample_size": 48,
                "baseline_p50_days": 32,
                "baseline_p80_days": 39,
                "baseline_p90_days": 45,
                "on_time_delivery_rate": 0.78,
            },
            "source_observation_ids": ["QNT_OBS_001"],
        }
    )


def _profile_values(**changes) -> dict:
    values = {
        "quantile_contract_version": QUANTILE_CONTRACT_VERSION,
        "numeric_profile_id": NUMERIC_PROFILE_ID,
        "unit": UNIT,
        "day_basis": DAY_BASIS,
        "p50_days": 58,
        "p80_days": 68.44,
        "p90_days": 78.3,
    }
    values.update(changes)
    return values


def test_quantile_numeric_boundary_entrypoint_exists() -> None:
    module = importlib.import_module("gltg.contracts.numeric_boundary")
    required = {
        "QuantileProfileDocument",
        "build_quantile_document",
        "quantile_canonical_sha256",
        "project_post_resolution_numeric_input",
        "actual_input_snapshot_sha256",
    }
    assert required <= set(dir(module))


def test_profile_identifiers_and_closed_key_set_are_exact() -> None:
    assert QUANTILE_CONTRACT_VERSION == "gltg.quantile-json-number.v1"
    assert NUMERIC_PROFILE_ID == "gltg.quantiles.duration.v1"
    assert UNIT == "day"
    assert DAY_BASIS == "UNSPECIFIED"
    assert QUANTILE_DOCUMENT_FIELDS == set(_profile_values())


def test_primary_vector_has_accepted_new_bytes_and_hash() -> None:
    document = build_quantile_document(
        GLTGQuantiles(p50_days=58, p80_days=68.44, p90_days=78.3)
    )
    canonical = rfc8785_bytes(document.model_dump(mode="json"))
    assert canonical == PRIMARY_CANONICAL
    assert len(canonical) == 196
    assert hashlib.sha256(canonical).hexdigest() == PRIMARY_SHA256
    assert quantile_canonical_sha256(document) == PRIMARY_SHA256
    assert PRIMARY_SHA256 != "fed6538e753dff8ea10fa911a91b27895fd09c61072108ef4054dfc670ffd745"


@pytest.mark.parametrize("p50", [58, 58.0, 5.8e1])
def test_integral_numeric_spellings_share_one_digest(p50: float) -> None:
    document = QuantileProfileDocument(**_profile_values(p50_days=p50))
    assert quantile_canonical_sha256(document) == PRIMARY_SHA256


@pytest.mark.parametrize(
    ("quantiles", "expected"),
    [
        ((-0.0, 0.0, 0.0), b'"p50_days":0,"p80_days":0,"p90_days":0'),
        ((1e30, 1e30, 1e30), b'"p50_days":1e+30,"p80_days":1e+30,"p90_days":1e+30'),
        ((1e-27, 1e-27, 1e-27), b'"p50_days":1e-27,"p80_days":1e-27,"p90_days":1e-27'),
        ((5e-324, 5e-324, 1e-323), b'"p50_days":5e-324,"p80_days":5e-324,"p90_days":1e-323'),
        (
            (1.23456789, 2.34567891, 3.45678912),
            b'"p50_days":1.23456789,"p80_days":2.34567891,"p90_days":3.45678912',
        ),
    ],
)
def test_binary64_boundary_vectors(quantiles: tuple[float, float, float], expected: bytes) -> None:
    document = QuantileProfileDocument(
        **_profile_values(
            p50_days=quantiles[0], p80_days=quantiles[1], p90_days=quantiles[2]
        )
    )
    assert expected in rfc8785_bytes(document.model_dump(mode="json"))


@pytest.mark.parametrize(
    "changes",
    [
        {"p50_days": -0.01},
        {"p50_days": 2, "p80_days": 1.9},
        {"p80_days": 4, "p90_days": 3},
        {"p50_days": float("nan")},
        {"p90_days": float("inf")},
        {"p50_days": True},
    ],
)
def test_invalid_quantile_values_fail_closed(changes: dict) -> None:
    with pytest.raises(ValidationError):
        QuantileProfileDocument(**_profile_values(**changes))


def test_digest_is_external_and_recursive_or_extra_fields_are_rejected() -> None:
    values = _profile_values()
    values["quantile_canonical_sha256"] = "00" * 32
    with pytest.raises(ValidationError):
        QuantileProfileDocument.model_validate(values)
    with pytest.raises(ValidationError):
        quantile_canonical_sha256({**_profile_values(), "extra": True})


@pytest.mark.parametrize(
    ("value", "canonical", "digest"),
    [
        (
            [333333333.3333333, 1e30, 4.5, 0.002, 1e-27, -0.0],
            b"[333333333.3333333,1e+30,4.5,0.002,1e-27,0]",
            "3c9384fb0690970a0df3b40b3cc762ff1b9c9efbd41daeda39db4b2eae1a6cb4",
        ),
        (
            {"z": "line\nquote\"slash\\", "é": "€"},
            "{\"z\":\"line\\nquote\\\"slash\\\\\",\"é\":\"€\"}".encode(),
            "8a283a2bd57f0fbf689c53952a03356d3d26143bd1010342b419cd9fa5dee7b6",
        ),
        (
            {"😀": "grin", "€": "euro", "\r": "cr", "1": "one", "ö": "o"},
            "{\"\\r\":\"cr\",\"1\":\"one\",\"ö\":\"o\",\"€\":\"euro\",\"😀\":\"grin\"}".encode(),
            "3c79ba5d6298bf77f49a53a5fda4816b0e435761d756be9040b2c0b7ffe316d9",
        ),
    ],
)
def test_rfc8785_external_golden_vectors(value, canonical: bytes, digest: str) -> None:
    actual = rfc8785_bytes(value)
    assert actual == canonical
    assert hashlib.sha256(actual).hexdigest() == digest


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "\ud800"])
def test_rfc8785_rejects_non_json_values(value) -> None:
    with pytest.raises(CanonicalizationError):
        rfc8785_bytes(value)


def test_rfc8785_accepts_exact_binary64_integer_above_safe_distinctness_range() -> None:
    assert rfc8785_bytes(2**53) == b"9007199254740992"


def test_rfc8785_rejects_integer_not_exactly_representable_as_binary64() -> None:
    with pytest.raises(CanonicalizationError, match="binary64"):
        rfc8785_bytes(2**53 + 1)
    with pytest.raises(ValidationError, match="binary64"):
        QuantileProfileDocument(**_profile_values(p90_days=2**53 + 1))


def test_post_resolution_projection_is_closed_and_excludes_volatile_metadata() -> None:
    req = _request()
    projection = project_post_resolution_numeric_input(req)
    assert tuple(projection) == POST_RESOLUTION_NUMERIC_INPUT_FIELDS
    assert set(projection) == {
        "order",
        "supplier",
        "historical_baseline",
        "behavior_features",
        "trade_processing_factors",
        "source_observation_ids",
        "constraints",
    }
    assert not {
        "request_id",
        "tenant_id",
        "source_system",
        "source_trace_id",
        "case_context",
        "evidence",
        "model_provider",
    } & set(projection)


def test_volatile_request_metadata_does_not_change_numeric_input_hash() -> None:
    first = _request()
    second = _request()
    second.request_id = "different-request"
    second.source_trace_id = "different-trace"
    second.source_system = "different-system"
    assert actual_input_snapshot_sha256(first) == actual_input_snapshot_sha256(second)


def test_business_input_changes_numeric_input_hash() -> None:
    first = _request()
    second = _request()
    second.historical_baseline.baseline_p80_days = 49
    assert actual_input_snapshot_sha256(first) != actual_input_snapshot_sha256(second)


def test_actual_input_hash_uses_named_domain_and_rfc8785_bytes() -> None:
    req = _request()
    expected = hashlib.sha256(
        f"{ACTUAL_INPUT_DOMAIN}\n".encode()
        + rfc8785_bytes(project_post_resolution_numeric_input(req))
    ).hexdigest()
    assert actual_input_snapshot_sha256(req) == expected


def test_projection_observes_values_applied_by_evidence_resolution() -> None:
    class EvidenceClient:
        def get_supplier(self, supplier_id: str, tenant_id: str) -> dict:
            assert supplier_id == "requirement"
            assert tenant_id == "tenant_qnt_green"
            return {"name_en": "Resolved Supplier", "active": True, "is_synthetic": True}

        def get_supplier_behavior_summary(self, supplier_id: str, tenant_id: str) -> dict:
            assert supplier_id == "requirement"
            assert tenant_id == "tenant_qnt_green"
            return {
                "observation_count": 1,
                "latest_snapshot": {
                    "snapshot_id": "QNT_RESOLVED_OBS_002",
                    "feature_json": {"response_delay_ratio": 1.25},
                },
            }

    req = _request()
    req.evidence.use_giraffe_db = True
    before = actual_input_snapshot_sha256(req)
    resolve_evidence(req, EvidenceClient())
    projection = project_post_resolution_numeric_input(req)

    assert projection["supplier"]["name"] == "Resolved Supplier"
    assert projection["behavior_features"]["supplier"]["response_delay_ratio"] == 1.25
    assert "QNT_RESOLVED_OBS_002" in projection["source_observation_ids"]
    assert actual_input_snapshot_sha256(req) != before


def test_post_evaluation_evidence_risk_change_does_not_relabel_numeric_input() -> None:
    req = _request()
    before = actual_input_snapshot_sha256(req)
    response = evaluate(req)
    degraded = ResolvedEvidence()
    degraded.confidence_penalty = 0.1
    degraded.force_manual_review = True
    degraded.explanation = {
        "evidence": {"behavior_evidence_status": "endpoint_unavailable"}
    }
    original_confidence = response.risk.confidence_score
    _apply_evidence_to_response(response, degraded)
    assert actual_input_snapshot_sha256(req) == before
    assert response.risk.confidence_score != original_confidence
    assert response.manual_review_required is True


def test_legacy_v2_response_is_not_silently_upgraded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLTG_EVALUATOR_MODE", "deterministic")
    payload = evaluate(copy.deepcopy(_request())).model_dump(mode="json")
    assert set(payload["quantiles"]) == {"p50_days", "p80_days", "p90_days"}
    assert "quantile_canonical_sha256" not in payload
    assert "actual_input_snapshot_sha256" not in payload
    assert all(math.isfinite(value) for value in payload["quantiles"].values())
