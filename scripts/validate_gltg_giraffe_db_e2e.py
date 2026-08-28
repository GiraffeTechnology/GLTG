#!/usr/bin/env python3
"""Real-HTTP end-to-end proof: GLTG v2 consuming live giraffe-db evidence.

Chain (no fixtures, no monkey-patched clients, no static JSON, no mocked HTTP):

    fresh giraffe-db service DB (SQLite file)
    -> alembic migrations
    -> synthetic supplier import (loaders.import_suppliers_to_app_db)
    -> live giraffe-db uvicorn (service auth enforced)
    -> live GLTG uvicorn configured with GLTG_GIRAFFE_DB_BASE_URL
    -> authenticated evidence retrieval inside POST /v2/lead-time/simulate
    -> quantile/risk/explanation output
    -> persisted run in giraffe-db (gltg_simulation_runs)
    -> persisted-run verification (direct row check in the fresh DB)
    -> tenant isolation, fail-closed auth, DB_UNAVAILABLE checks

Requires a giraffe-db checkout (Stage 2A or later). Default location is a
sibling directory; override with GIRAFFE_DB_REPO.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

GLTG_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GDB_REPO = GLTG_ROOT.parent / "giraffe-db"

SUPPLIER_ID = "GDB_SYN_V1_SUP_000001"
TENANT = "tenant-demo"
WRONG_TENANT = "tenant-other"

RESULTS: list[dict[str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append({"check": name, "status": "PASS" if condition else "FAIL", "detail": detail})
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_healthy(client: httpx.Client, url: str, attempts: int = 100) -> bool:
    for _ in range(attempts):
        try:
            if client.get(url).status_code == 200:
                return True
        except httpx.TransportError:
            time.sleep(0.2)
    return False


def main() -> int:
    gdb_repo = Path(os.environ.get("GIRAFFE_DB_REPO", str(DEFAULT_GDB_REPO)))
    if not (gdb_repo / "alembic.ini").exists():
        print(f"giraffe-db repo not found at {gdb_repo}; set GIRAFFE_DB_REPO")
        return 2

    tmpdir = tempfile.TemporaryDirectory(prefix="gltg_gdb_e2e_")
    db_path = Path(tmpdir.name) / "giraffe_db_e2e.sqlite3"
    database_url = f"sqlite+pysqlite:///{db_path}"
    gdb_secret = secrets.token_hex(16)
    inbound_secret = secrets.token_hex(16)

    gdb_env = {
        **os.environ,
        "GIRAFFE_DB_DATABASE_URL": database_url,
        "GIRAFFE_DB_SERVICE_AUTH_SECRET": gdb_secret,
    }

    print("== giraffe-db: fresh DB via alembic + supplier import ==")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True, cwd=gdb_repo, env=gdb_env,
    )
    subprocess.run(
        [
            sys.executable, "-m", "loaders.import_suppliers_to_app_db",
            "--dataset", str(gdb_repo / "datasets" / "synthetic_private_v1"),
            "--database-url", database_url,
            "--tenant-id", TENANT,
            "--skip-validation",
        ],
        check=True, cwd=gdb_repo, env=gdb_env,
    )

    gdb_port = free_port()
    gltg_port = free_port()
    gltg_port_badauth = free_port()
    gdb_base = f"http://127.0.0.1:{gdb_port}"

    gdb_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "giraffe_db.api.main:app",
         "--host", "127.0.0.1", "--port", str(gdb_port)],
        cwd=gdb_repo, env=gdb_env,
    )
    gltg_env = {
        **os.environ,
        "GLTG_GIRAFFE_DB_BASE_URL": gdb_base,
        "GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET": gdb_secret,
        "GLTG_INBOUND_SERVICE_AUTH_SECRET": inbound_secret,
        "GLTG_PERSIST_RUNS": "true",
    }
    gltg_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "gltg.api.main:app",
         "--host", "127.0.0.1", "--port", str(gltg_port)],
        cwd=GLTG_ROOT, env=gltg_env,
    )
    gltg_badauth_env = {**gltg_env, "GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET": "wrong-secret"}
    gltg_badauth_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "gltg.api.main:app",
         "--host", "127.0.0.1", "--port", str(gltg_port_badauth)],
        cwd=GLTG_ROOT, env=gltg_badauth_env,
    )

    payload = {
        "request_id": "E2E-GDB-1",
        "tenant_id": TENANT,
        "order": {"product_type": "t-shirt", "quantity": 10000, "deadline_days": 150},
        "supplier": {
            "supplier_id": SUPPLIER_ID,
            "capacity_per_day": 800,
            "material_ready_days": 7,
            "production_days": 14,
            "qc_days": 3,
            "logistics_days": 20,
            "confidence": 0.8,
        },
        "evidence": {"use_giraffe_db": True},
        "source_observation_ids": [],
    }
    gltg_headers = {
        "X-Service-Auth": inbound_secret,
        "X-Service-Tenant-ID": TENANT,
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            if not wait_healthy(client, f"{gdb_base}/healthz"):
                check("giraffe-db startup", False)
                return finish()
            gltg_base = f"http://127.0.0.1:{gltg_port}"
            if not wait_healthy(client, f"{gltg_base}/health"):
                check("GLTG startup", False)
                return finish()
            check("both services live over real HTTP", True)

            ready = client.get(f"{gltg_base}/ready").json()
            check(
                "GLTG /ready reports giraffe-db ok without secrets",
                ready.get("giraffe_db") == "ok" and gdb_secret not in json.dumps(ready),
                json.dumps(ready),
            )

            # giraffe-db fail-closed spot checks (real HTTP).
            check(
                "giraffe-db missing auth fails closed (401)",
                client.get(
                    f"{gdb_base}/api/data/suppliers/{SUPPLIER_ID}",
                    headers={"X-Service-Tenant-ID": TENANT},
                ).status_code == 401,
            )
            check(
                "giraffe-db wrong tenant cannot read supplier (404)",
                client.get(
                    f"{gdb_base}/api/data/suppliers/{SUPPLIER_ID}",
                    headers={"X-Service-Auth": gdb_secret, "X-Service-Tenant-ID": WRONG_TENANT},
                ).status_code == 404,
            )

            # The central chain: GLTG v2 with live giraffe-db evidence.
            response = client.post(
                f"{gltg_base}/v2/lead-time/simulate",
                json=payload,
                headers=gltg_headers,
            )
            body = response.json() if response.status_code == 200 else {}
            check("GLTG v2 simulate with evidence is 200", response.status_code == 200)
            quantiles = body.get("quantiles", {})
            check(
                "quantiles are real and monotonic",
                0 < quantiles.get("p50_days", 0) <= quantiles.get("p80_days", 0) <= quantiles.get("p90_days", 0),
                json.dumps(quantiles),
            )
            evidence_meta = body.get("explanation_json", {}).get("evidence", {})
            check(
                "supplier record + behavior summary retrieved from giraffe-db",
                set(evidence_meta.get("retrieved", [])) == {"supplier_record", "behavior_summary"},
                json.dumps(evidence_meta),
            )
            codes = {w["code"] for w in body.get("warnings", [])}
            check("synthetic evidence disclosed", "SYNTHETIC_EVIDENCE" in codes, str(sorted(codes)))
            check(
                "missing behavior evidence disclosed (no invention)",
                "MISSING_BEHAVIOR_EVIDENCE" in codes,
            )
            check(
                "deterministic evaluation mode",
                body.get("evaluation_mode") == "deterministic",
            )

            persistence = body.get("persistence", {})
            run_row_ok = False
            persisted_id = persistence.get("giraffe_db_run_id")
            if persisted_id:
                conn = sqlite3.connect(str(db_path))
                try:
                    row = conn.execute(
                        "SELECT tenant_id, supplier_id, final_p50_days FROM gltg_simulation_runs "
                        "WHERE gltg_run_id = ?",
                        (persisted_id,),
                    ).fetchone()
                finally:
                    conn.close()
                run_row_ok = (
                    row is not None
                    and row[0] == TENANT
                    and row[1] == SUPPLIER_ID
                    and abs(float(row[2]) - quantiles.get("p50_days", -1)) < 0.01
                )
            check(
                "run persisted to giraffe-db and verified in the fresh DB",
                persistence.get("status") == "persisted" and run_row_ok,
                json.dumps(persistence),
            )

            # Determinism of the calculation across repeated calls.
            body2 = client.post(
                f"{gltg_base}/v2/lead-time/simulate",
                json=payload,
                headers=gltg_headers,
            ).json()
            check(
                "repeated call: identical run id, quantiles and risk",
                body2.get("gltg_run_id") == body.get("gltg_run_id")
                and body2.get("quantiles") == body.get("quantiles")
                and body2.get("risk") == body.get("risk"),
            )

            # Wrong tenant through GLTG: isolation, explicit missing evidence.
            wrong = client.post(
                f"{gltg_base}/v2/lead-time/simulate",
                json={**payload, "request_id": "E2E-GDB-WT", "tenant_id": WRONG_TENANT},
                headers={
                    "X-Service-Auth": inbound_secret,
                    "X-Service-Tenant-ID": WRONG_TENANT,
                },
            )
            wrong_body = wrong.json()
            check(
                "wrong tenant cannot read evidence via GLTG (explicit EVIDENCE_NOT_FOUND)",
                wrong.status_code == 200
                and any(w["code"] == "EVIDENCE_NOT_FOUND" for w in wrong_body.get("warnings", []))
                and wrong_body["risk"]["manual_review_required"] is True,
            )

            # GLTG configured with a wrong service secret must fail closed.
            gltg_badauth_base = f"http://127.0.0.1:{gltg_port_badauth}"
            if wait_healthy(client, f"{gltg_badauth_base}/health"):
                bad = client.post(
                    f"{gltg_badauth_base}/v2/lead-time/simulate",
                    json={**payload, "request_id": "E2E-GDB-BAD"},
                    headers=gltg_headers,
                )
                check(
                    "wrong GLTG service secret fails closed (502 EVIDENCE_AUTH_FAILED)",
                    bad.status_code == 502 and bad.json().get("code") == "EVIDENCE_AUTH_FAILED",
                )
            else:
                check("wrong-secret GLTG instance startup", False)

            # Impossible deadline scenario: infeasible + manual review, no crash.
            impossible = client.post(
                f"{gltg_base}/v2/lead-time/simulate",
                json={
                    **payload,
                    "request_id": "E2E-GDB-DEADLINE",
                    "order": {"product_type": "t-shirt", "quantity": 10000, "deadline_days": 2},
                    "constraints": {"manual_review_policy": "required_if_deadline_tight"},
                },
                headers=gltg_headers,
            ).json()
            check(
                "impossible deadline: infeasible + high risk + manual review",
                impossible["risk"]["deadline_feasible"] is False
                and impossible["risk"]["deadline_risk_level"] == "high"
                and impossible["risk"]["manual_review_required"] is True,
            )

            # Reforecast with a capacity/logistics change over live evidence.
            reforecast = client.post(
                f"{gltg_base}/v2/reforecast",
                json={
                    **payload,
                    "request_id": "E2E-GDB-REF",
                    "events": [
                        {"event_type": "capacity_update", "capacity_utilization_ratio": 0.95},
                        {"event_type": "logistics_disruption", "freight_space_risk": 0.9},
                    ],
                },
                headers=gltg_headers,
            ).json()
            check(
                "reforecast applies events and discloses previous vs new quantiles",
                reforecast.get("applied_events")
                and reforecast.get("previous_quantiles") is not None
                and reforecast["quantiles"]["p90_days"] >= reforecast["previous_quantiles"]["p90_days"]
                and reforecast.get("changed_components"),
                json.dumps(reforecast.get("delta")),
            )

            # DB down mid-flight: explicit DB_UNAVAILABLE, no silent fallback.
            gdb_proc.terminate()
            gdb_proc.wait(timeout=10)
            down = client.post(
                f"{gltg_base}/v2/lead-time/simulate",
                json={**payload, "request_id": "E2E-GDB-DOWN"},
                headers=gltg_headers,
            )
            check(
                "giraffe-db down: explicit 503 DB_UNAVAILABLE (no silent fallback)",
                down.status_code == 503 and down.json().get("code") == "DB_UNAVAILABLE",
            )
    finally:
        for proc in (gdb_proc, gltg_proc, gltg_badauth_proc):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
        tmpdir.cleanup()

    return finish()


def finish() -> int:
    failed = [result for result in RESULTS if result["status"] == "FAIL"]
    print(json.dumps({"checks": len(RESULTS), "failed": len(failed)}))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
