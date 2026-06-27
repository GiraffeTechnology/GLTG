"""Exercises the GLTG HTTP API edge cases in-process (0/1/2/3+ suppliers).

Uses FastAPI's TestClient so no running server is required.

Run from the GLTG/ directory:
    python scripts/run_api_edge_cases.py
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from gltg.api.main import app  # noqa: E402

client = TestClient(app)


def _supplier(sid: str) -> dict:
    return {
        "supplier_id": sid,
        "name": f"Supplier {sid}",
        "capacity_per_day": 800,
        "material_ready_days": 5,
        "production_days": 14,
        "qc_days": 2,
        "logistics_days": 7,
        "confidence": 0.8,
    }


def run_case(label: str, n: int) -> bool:
    suppliers = [_supplier(f"S{i}") for i in range(n)]
    payload = {"order": {"quantity": 10000}, "suppliers": suppliers}
    est = client.post("/v1/lead-time/estimate", json=payload).json()
    paths = client.post("/v1/paths/enumerate", json=payload).json()
    codes = {w["code"] for w in est["warnings"]}
    print(f"\n=== {label} ({n} suppliers) ===")
    print(f"  estimate.feasible           : {est['feasible']}")
    print(f"  estimate.supplier_count     : {est['supplier_count']}")
    print(f"  estimate.estimated_lead_days: {est['estimated_lead_time_days']}")
    print(f"  estimate.warnings           : {sorted(codes)}")
    print(f"  paths.count                 : {len(paths['paths'])}")

    ok = est["supplier_count"] == n
    if n == 0:
        ok = ok and est["feasible"] is False and est["estimated_lead_time_days"] is None
        ok = ok and "NO_SUPPLIERS" in codes and paths["paths"] == []
    elif n == 1:
        ok = ok and "LIMITED_COMPARISON" in codes
    elif n == 2:
        ok = ok and "LIMITED_SUPPLIER_POOL" in codes
    else:
        ok = ok and "LIMITED_COMPARISON" not in codes and "LIMITED_SUPPLIER_POOL" not in codes
    print(f"  [{'PASS' if ok else 'FAIL'}]")
    return ok


def main() -> None:
    print("=" * 60)
    print("GLTG API SUPPLIER EDGE CASES (0 / 1 / 2 / 3+)")
    print("=" * 60)
    results = [
        run_case("ZERO", 0),
        run_case("ONE", 1),
        run_case("TWO", 2),
        run_case("THREE_PLUS", 4),
    ]
    print("\n" + "=" * 60)
    if all(results):
        print("GLTG API EDGE CASES: PASS")
    else:
        print("GLTG API EDGE CASES: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
