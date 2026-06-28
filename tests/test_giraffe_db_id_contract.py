"""giraffe-db unified ID contract in GLTG lead-time traces.

GLTG receives supplier ids opaquely and mints none of its own giraffe-db record
ids. These tests pin that no retired giraffe-db legacy id appears in the repo and
that a canonical giraffe-db supplier id flows through GLTG's source traces
verbatim, never rewritten to a legacy form.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from gltg.api.schemas import LeadTimeEstimateResponse, SupplierTrace

_REPO_ROOT = Path(__file__).resolve().parent.parent

CANONICAL_RE = re.compile(r"^GDB_SYN_V1_(?:SUP|PROD|CAP|CUST|PREF|RFQ|QUOTE|OBS|RISK)_[0-9]{6}$")
LEGACY_RE = re.compile(r"_SYN_[0-9]{3,}$")


def test_no_legacy_giraffe_db_ids_in_repo():
    result = subprocess.run(
        [sys.executable, "scripts/check_unified_data_ids.py", "--repo", "."],
        cwd=_REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RESULT: PASS" in result.stdout


def test_supplier_trace_preserves_canonical_id():
    canonical = "GDB_SYN_V1_SUP_000001"
    trace = SupplierTrace(
        supplier_id=canonical,
        material_ready_days=3.0,
        production_days=10.0,
        capacity_adjusted_production_days=11.0,
        qc_days=2.0,
        logistics_days=20.0,
        total_lead_time_days=46.0,
        confidence=0.8,
        feasible=True,
    )
    resp = LeadTimeEstimateResponse(
        selected_supplier_id=canonical,
        supplier_count=1,
        calculation_trace=[trace],
    )
    assert resp.selected_supplier_id == canonical
    assert resp.calculation_trace[0].supplier_id == canonical
    assert CANONICAL_RE.match(resp.selected_supplier_id)
    assert not LEGACY_RE.search(resp.calculation_trace[0].supplier_id)
