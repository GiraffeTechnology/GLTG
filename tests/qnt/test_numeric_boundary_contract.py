from __future__ import annotations

import importlib


def test_quantile_numeric_boundary_entrypoint_exists() -> None:
    try:
        module = importlib.import_module("gltg.contracts.numeric_boundary")
    except ModuleNotFoundError as exc:
        assert False, (
            "QNT_NUMERIC_BOUNDARY_ENTRYPOINT_MISSING: "
            "gltg.contracts.numeric_boundary must be implemented"
        ) from exc

    required = {
        "QuantileProfileDocument",
        "build_quantile_document",
        "quantile_canonical_sha256",
        "project_post_resolution_numeric_input",
        "actual_input_snapshot_sha256",
    }
    assert required <= set(dir(module)), "QNT_NUMERIC_BOUNDARY_ENTRYPOINT_INCOMPLETE"
