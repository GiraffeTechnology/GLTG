#!/usr/bin/env python3
"""Prove the API extra alone provides the complete runtime.

Creates a throwaway virtualenv, installs ONLY ``.[api]`` (no dev extras),
then — inside that venv — imports ``gltg.api.main`` and the giraffe-db
client, boots uvicorn, and checks ``/health``, ``/ready`` and a
deterministic ``/v2/lead-time/simulate`` over real HTTP. Guards against
runtime imports leaking into dev-only dependencies (the Docker image
installs exactly ``.[api]``).

Success in a dev environment is deliberately not trusted: everything runs
with the clean venv's interpreter.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http_json(
    url: str,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    request_headers = {"content-type": "application/json"} if data else {}
    request_headers.update(headers or {})
    request = urllib.request.Request(
        url, data=data, headers=request_headers
    )
    with urllib.request.urlopen(request, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode())


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="gltg_api_only_") as tmp:
        venv_dir = Path(tmp) / "venv"
        print(f"== creating clean venv: {venv_dir}")
        venv.create(venv_dir, with_pip=True)
        python = venv_dir / "bin" / "python"

        print("== installing ONLY .[api] (no dev extras)")
        subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet", f"{REPO_ROOT}[api]"],
            check=True,
        )

        print("== import check inside the clean venv")
        import_check = subprocess.run(
            [
                str(python),
                "-c",
                "import gltg.api.main, gltg.integrations.giraffe_db_client; "
                "print('imports ok')",
            ],
            capture_output=True,
            text=True,
        )
        print(import_check.stdout.strip() or import_check.stderr.strip())
        if import_check.returncode != 0:
            print("FAIL: gltg.api.main is not importable with only .[api] installed")
            return 1

        port = free_port()
        server = subprocess.Popen(
            [str(python), "-m", "uvicorn", "gltg.api.main:app",
             "--host", "127.0.0.1", "--port", str(port)],
            cwd=tmp,  # deliberately NOT the repo root: no source-tree fallback
            env={**os.environ, "GLTG_INBOUND_SERVICE_AUTH_SECRET": "api-only-secret"},
        )
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(60):
                try:
                    status, health = http_json(f"{base}/health")
                    if status == 200:
                        break
                except OSError:
                    time.sleep(0.5)
            else:
                print("FAIL: server did not become healthy")
                return 1

            if health.get("status") != "ok":
                failures.append(f"/health body unexpected: {health}")
            status, ready = http_json(f"{base}/ready")
            if status != 200 or "ready" not in ready or ready.get("giraffe_db") != "not_configured":
                failures.append(f"/ready unexpected: HTTP {status} {ready}")
            status, body = http_json(
                f"{base}/v2/lead-time/simulate",
                {
                    "request_id": "API-ONLY-1",
                    "tenant_id": "api-only-tenant",
                    "order": {"product_type": "t-shirt", "quantity": 1000},
                },
                {
                    "X-Service-Auth": "api-only-secret",
                    "X-Service-Tenant-ID": "api-only-tenant",
                },
            )
            quantiles = body.get("quantiles", {})
            if status != 200 or body.get("evaluation_mode") != "deterministic":
                failures.append(f"v2 simulate unexpected: HTTP {status} mode={body.get('evaluation_mode')}")
            elif not (0 < quantiles.get("p50_days", 0) <= quantiles.get("p80_days", 0) <= quantiles.get("p90_days", 0)):
                failures.append(f"v2 quantiles unexpected: {quantiles}")
        finally:
            server.terminate()
            server.wait(timeout=10)

    for failure in failures:
        print(f"FAIL: {failure}")
    print(f"API-only runtime check: {'FAIL' if failures else 'PASS'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
