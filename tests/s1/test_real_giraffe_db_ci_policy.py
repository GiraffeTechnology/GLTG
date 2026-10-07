from __future__ import annotations

import re
from pathlib import Path


WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "ci.yml"
PINNED_GIRAFFE_DB_REVISION = "88b4c660e2aec7479826527456e41ec417dc6e28"


def _real_http_job() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    start = workflow.index("  giraffe-db-e2e:")
    end = workflow.index("\n  docker:", start)
    return workflow[start:end]


def test_real_http_job_is_fail_closed_and_immutable() -> None:
    job = _real_http_job()

    assert f"GIRAFFE_DB_REVISION: {PINNED_GIRAFFE_DB_REVISION}" in job
    assert re.search(r'test "\$\{#GIRAFFE_DB_REVISION\}" -eq 40', job)
    assert "exit 1" in job
    assert "available=true" not in job
    assert "available=false" not in job
    assert "if: steps.gdb.outputs.available" not in job


def test_private_checkout_does_not_embed_the_token_and_runs_real_steps() -> None:
    job = _real_http_job()

    assert "https://x-access-token:" not in job
    assert "repository: GiraffeTechnology/giraffe-db" in job
    assert "ref: ${{ env.GIRAFFE_DB_REVISION }}" in job
    assert "persist-credentials: false" in job
    assert 'git -C giraffe-db rev-parse HEAD' in job
    assert 'GIRAFFE_DB_REPO: ${{ github.workspace }}/giraffe-db' in job
    assert "python scripts/validate_gltg_giraffe_db_e2e.py" in job
