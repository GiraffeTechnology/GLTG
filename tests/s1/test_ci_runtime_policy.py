from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_checks_use_authenticated_tenant_bound_requests() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    runtime = (ROOT / "scripts" / "validate_api_only_runtime.py").read_text(encoding="utf-8")

    assert "X-Service-Auth" in workflow
    assert "X-Service-Tenant-ID" in workflow
    assert '"tenant_id":"ci-only-tenant"' in workflow
    assert "GLTG_INBOUND_SERVICE_AUTH_SECRET" in runtime
    assert '"tenant_id": CI_TENANT' in runtime


def test_real_http_e2e_cannot_succeed_by_skipping_implementation_steps() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "GIRAFFE_DB_REVISION: eddf76fbab21ecf32323187bd7a27e3dd819d1d7" in workflow
    assert 'test -n "$GIRAFFE_DB_CI_TOKEN"' in workflow
    assert "persist-credentials: false" in workflow
    assert "Verify exact giraffe-db revision" in workflow
    assert "if: steps.gdb.outputs.available" not in workflow
    assert "x-access-token" not in workflow
