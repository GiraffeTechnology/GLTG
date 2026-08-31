"""Fail-closed policy checks for the required real giraffe-db HTTP E2E job."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW_PATH = Path(__file__).parents[2] / ".github" / "workflows" / "ci.yml"


def _real_e2e_job() -> str:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"(?ms)^  giraffe-db-e2e:\n(?P<job>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        workflow,
    )
    assert match is not None, "required giraffe-db-e2e job is missing"
    return match.group("job")


def test_real_e2e_job_is_pinned_to_an_immutable_revision() -> None:
    job = _real_e2e_job()
    revision = re.search(r"(?m)^    GIRAFFE_DB_REVISION: ([0-9a-f]{40})$", job)

    assert revision is not None, "giraffe-db E2E must pin an exact 40-hex revision"
    assert "ref: ${{ env.GIRAFFE_DB_REVISION }}" in job
    assert "git rev-parse HEAD" in job


def test_real_e2e_substantive_steps_cannot_be_skipped_successfully() -> None:
    job = _real_e2e_job()

    for step_name in (
        "Clone giraffe-db at accepted revision",
        "Install GLTG + giraffe-db",
        "Real HTTP E2E (GLTG <-> giraffe-db)",
    ):
        assert f"- name: {step_name}" in job

    assert "steps.gdb.outputs.available" not in job
    assert "available=false" not in job
    assert "continue-on-error:" not in job
    assert "if: always()" not in job
    assert "if: success()" not in job


def test_missing_credentials_and_repository_access_fail_closed_without_leakage() -> None:
    job = _real_e2e_job()

    assert "- name: Require giraffe-db credential" in job
    assert 'if [[ -z "${GIRAFFE_DB_CI_TOKEN:-}" ]]' in job
    assert "exit 1" in job
    assert "token: ${{ secrets.GIRAFFE_DB_CI_TOKEN }}" in job
    assert "persist-credentials: false" in job

    # Never embed the credential into a URL/command or print its value.
    assert "x-access-token" not in job
    assert not re.search(r"echo[^\n]*\$\{?GIRAFFE_DB_CI_TOKEN", job)


def test_clone_install_and_real_e2e_failures_propagate_to_the_required_job() -> None:
    job = _real_e2e_job()

    # GitHub's default step semantics are fail-fast. These escape hatches could
    # turn a failed or skipped substantive step into a green required job.
    assert "continue-on-error:" not in job
    assert "if: always()" not in job
    assert "if: failure()" not in job
    assert "if: cancelled()" not in job
    assert "|| true" not in job
    assert "exit 0" not in job
    assert "GIRAFFE_DB_REVISION: main" not in job
    assert "GIRAFFE_DB_REVISION: master" not in job
