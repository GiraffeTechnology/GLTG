"""The integration job must execute the actual selected HTTP/MySQL path."""
from pathlib import Path

WORKFLOW = Path(__file__).parents[2] / ".github/workflows/ci.yml"


def _job():
    text = WORKFLOW.read_text()
    start = text.index("  giraffe-db-e2e:")
    return text[start:text.index("\n  docker:", start)]


def test_selected_http_dependencies_are_exact_and_verified():
    job = _job()
    revisions = {
        "GIRAFFE_DB_REVISION": "ddbadf9038d70045e8ac8dac07903342a4c38d2c",
        "LANGUAGE_REVISION": "c4efcaea7cddfe3653fda7b7a3d2076b1e3bc302",
        "CONSUMER_REVISION": "beaec23663e8b8e78f82b4b90cec33db2cd1d283",
    }
    assert all(f"{key}: {value}" in job for key, value in revisions.items())
    for key in revisions:
        assert any(key in line and "rev-parse HEAD" in line for line in job.splitlines())


def test_actual_http_job_uses_mysql_migrations_language_and_consumer():
    job = _job()
    assert "services:\n      mysql:\n        image: mysql:" in job
    real = job.split("      - name: Real HTTP E2E", 1)[1].split("      - name:", 1)[0]
    assert "validate_private_provider_http.py" in real
    assert "--provider-repo" in real and "--language-repo" in real and "--consumer-repo" in real
    assert "--sqlite-supplement" not in real
    assert "if:" not in real and "continue-on-error" not in real
    assert "GLTG_ACCEPTANCE_DATABASE_URL: mysql+" in real
    assert "python -m pip install -e ./giraffe-language-skill" in job
