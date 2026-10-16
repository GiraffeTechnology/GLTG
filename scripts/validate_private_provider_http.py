#!/usr/bin/env python3
"""Actual language/DB/GLTG/consumer HTTP acceptance; no mocked transports.

An isolated MySQL DSN is read only from GLTG_ACCEPTANCE_DATABASE_URL. Local
SQLite execution requires the explicit --sqlite-supplement flag and cannot be
reported as CTYun/MySQL acceptance. All business reads and writes use DB APIs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def identity(repo):
    result = {}
    for field, revision in (("commit", "HEAD"), ("tree", "HEAD^{tree}")):
        result[field] = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", revision], text=True).strip()
    result["tracked_dirty"] = bool(subprocess.check_output(
        ["git", "-C", str(repo), "diff", "HEAD", "--", "src"], text=True))
    digest = hashlib.sha256()
    paths = subprocess.check_output(["git", "-C", str(repo), "ls-files", "src"], text=True).splitlines()
    for name in sorted(paths):
        path = repo / name
        if path.is_file():
            digest.update(name.encode() + b"\0" + path.read_bytes())
    result["runtime_source_sha256"] = digest.hexdigest()
    return result


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stop(process):
    if process.poll() is None:
        if os.name == "nt":
            # The Windows venv launcher may own an interpreter child; stop
            # only this runner-owned process tree before closing log handles.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, check=False)
            process.wait(timeout=10)
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def wait_ready(client, url):
    end = time.monotonic() + 45
    while time.monotonic() < end:
        try:
            if client.get(url).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(.1)
    raise RuntimeError("service_startup_timeout")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-repo", type=Path, required=True)
    parser.add_argument("--language-repo", type=Path, required=True)
    parser.add_argument("--consumer-repo", type=Path, required=True)
    parser.add_argument("--sqlite-supplement", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset_path = ROOT / "tests/fixtures/prd_http_dataset_v1.json"
    dataset_bytes = dataset_path.read_bytes()
    dataset = json.loads(dataset_bytes)
    report = {"schema": "gltg.private-provider-http-acceptance.v1", "checks": [],
              "sources": {"gltg": identity(ROOT), "provider": identity(args.provider_repo),
                          "language": identity(args.language_repo), "consumer": identity(args.consumer_repo)},
              "dataset": {"id": dataset["dataset_id"], "seed": dataset["seed"],
                          "bytes": len(dataset_bytes), "sha256": hashlib.sha256(dataset_bytes).hexdigest()},
              "production_deployed": False, "real_business_accuracy_claimed": False}

    def check(name, condition):
        report["checks"].append({"name": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)

    processes, handles = [], []
    ports = [free_port() for _ in range(3)]
    temp = tempfile.TemporaryDirectory(prefix="gltg_http_acceptance_")
    work = Path(temp.name)
    base_env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    def start(app, repo, port, env):
        log = (work / f"service-{port}.log").open("ab")
        handles.append(log)
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", app, "--host", "127.0.0.1",
                                    "--port", str(port), "--no-access-log"], cwd=repo,
                                   env={**env, "PYTHONPATH": str(repo / "src")}, stdout=log, stderr=log)
        processes.append(process)
        return process

    try:
        with httpx.Client(timeout=10, trust_env=False) as client:
            language_url, db_url, gltg_url = [f"http://127.0.0.1:{port}" for port in ports]
            # The canonical-English validation API is real. Translation/model
            # inference is outside this English-input acceptance run.
            start("giraffe_language_skill.api.main:app", args.language_repo, ports[0], base_env)
            wait_ready(client, language_url + "/healthz")
            if args.sqlite_supplement:
                dsn = "sqlite+pysqlite:///" + str(work / "supplement.sqlite3")
                report["database"] = "SQLite supplement; not MySQL or CTYun acceptance"
            else:
                dsn = os.environ.get("GLTG_ACCEPTANCE_DATABASE_URL", "")
                if not dsn.startswith("mysql+"):
                    raise RuntimeError("isolated_mysql_acceptance_configuration_required")
                report["database"] = "MySQL"
            tenant = "gltg-acceptance-" + secrets.token_hex(6)
            db_secret, inbound_secret = secrets.token_hex(24), secrets.token_hex(24)
            provider_env = {**base_env, "GIRAFFE_DB_DATABASE_URL": dsn,
                            "GIRAFFE_DB_SERVICE_AUTH_SECRET": db_secret,
                            "GIRAFFE_LANGUAGE_SKILL_URL": language_url,
                            "GIRAFFE_DB_REQUIRE_LANGUAGE_SKILL": "true"}
            migration_log = (work / "migration.log").open("ab")
            handles.append(migration_log)
            migration = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                                       check=False, cwd=args.provider_repo, env=provider_env,
                                       stdout=migration_log, stderr=migration_log, timeout=120)
            report["migration_exit"] = migration.returncode
            check("actual Alembic migration chain", migration.returncode == 0)
            provider = start("giraffe_db.api.main:app", args.provider_repo, ports[1], provider_env)
            wait_ready(client, db_url + "/healthz")
            db_headers = {"X-Service-Tenant-ID": tenant, "X-Service-Auth": db_secret}
            gltg_headers = {"X-Service-Tenant-ID": tenant, "X-Service-Auth": inbound_secret}
            gltg_env = {**base_env, "GLTG_GIRAFFE_DB_BASE_URL": db_url,
                        "GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET": db_secret,
                        "GLTG_INBOUND_SERVICE_AUTH_SECRET": inbound_secret,
                        "GLTG_PERSIST_RUNS": "true", "GLTG_EVALUATOR_MODE": "deterministic"}
            gltg = start("gltg.api.main:app", ROOT, ports[2], gltg_env)
            wait_ready(client, gltg_url + "/health")

            def create(path, body):
                response = client.post(db_url + "/api/data/" + path, json=body, headers=db_headers)
                if response.status_code not in {200, 201}:
                    report["provider_failure"] = {"operation": path, "http_status": response.status_code}
                    try:
                        result = response.json()
                        detail = result.get("detail", result)
                        if isinstance(detail, dict) and isinstance(detail.get("violations"), list):
                            report["language_violations"] = [{k: v for k, v in item.items() if k in {"field", "reason", "detected_language"}}
                                                             for item in detail["violations"]]
                    except ValueError:
                        pass
                    raise RuntimeError("provider_create_failed")
                return response.json()

            case = create("procurement-cases", {"status": "inquiry_received", "source_channel": "web",
                                                "metadata_json": {"dataset_id": dataset["dataset_id"], "seed": dataset["seed"]}})
            case_id = case["procurement_case_id"]
            payloads, results = [], []
            for index, scenario in enumerate(dataset["scenarios"]):
                supplier = create("suppliers", {"supplier_name": "Synthetic apparel manufacturer for integration testing",
                                                "name_en": "Synthetic apparel manufacturer for integration testing",
                                                "is_synthetic": True, "active": True})
                supplier_id = supplier["supplier_id"]
                obs = create("behavior-observations", {"entity_type": "supplier", "entity_id": supplier_id,
                    "behavior_type": "material_availability_pending", "source": "manual",
                    "procurement_case_id": case_id})
                factors = {name: value for name, value in scenario.items() if name != "name"}
                snapshot = create("behavior-feature-snapshots", {"entity_type": "supplier", "supplier_id": supplier_id,
                    "feature_window": "current", "procurement_case_id": case_id,
                    "source_observation_ids_json": [obs["behavior_observation_id"]],
                    "feature_json": {"trade_processing_factors": factors}})
                body = {"request_id": f"PRD-HTTP-{index}", "tenant_id": tenant,
                        "source_system": "aivan", "source_trace_id": f"PRD-TRACE-{index}",
                        "case_context": {"procurement_case_id": case_id, "assessment_scope": "supplier_candidate"},
                        "order": {"quantity": 100, "product_type": "t-shirt", "deadline_days": 1000},
                        "supplier": {"supplier_id": supplier_id, "capacity_per_day": 100},
                        "source_observation_ids": [obs["behavior_observation_id"]],
                        "evidence": {"use_giraffe_db": True}}
                response = client.post(gltg_url + "/v2/lead-time/simulate", json=body, headers=gltg_headers)
                check("scenario " + scenario["name"] + " HTTP success", response.status_code == 200)
                result = response.json()
                if result["persistence"]["status"] != "persisted":
                    report["persistence_failure"] = {"status": result["persistence"]["status"],
                                                     "detail": result["persistence"].get("detail")}
                check("scenario " + scenario["name"] + " API persistence readback", result["persistence"]["readback_status"] == "verified")
                q = result["quantiles"]
                check("scenario " + scenario["name"] + " monotonic quantiles", 0 <= q["p50_days"] <= q["p80_days"] <= q["p90_days"])
                check("scenario " + scenario["name"] + " snapshot lineage", snapshot["snapshot_id"] in result["source_observation_ids"])
                payloads.append(body); results.append(result)

            check("pending material widens tail", results[1]["quantiles"]["p90_days"] - results[1]["quantiles"]["p50_days"] >
                  results[0]["quantiles"]["p90_days"] - results[0]["quantiles"]["p50_days"])
            check("material reason is not low engagement", results[1]["risk_decomposition"]["engagement_risk"] == 0)
            check("unsupported fast quote requires review", results[2]["manual_review_required"] is True)
            body = payloads[0]
            graph_path = f"/api/data/procurement-cases/{case_id}/transaction-graph"
            before = client.get(db_url + graph_path, headers=db_headers).json()
            for _ in range(5):
                repeated = client.post(gltg_url + "/v2/lead-time/simulate", json=body, headers=gltg_headers).json()
                check("repeat canonical numbers and persistence ID", repeated["quantiles"] == results[0]["quantiles"] and
                      repeated["persistence"]["giraffe_db_run_id"] == results[0]["persistence"]["giraffe_db_run_id"])
            after = client.get(db_url + graph_path, headers=db_headers).json()
            check("effective idempotency prevents duplicate runs", len(before["gltg_runs"]) == len(after["gltg_runs"]))
            for headers, expected in (({}, 401), ({**gltg_headers, "X-Service-Auth": "wrong"}, 401),
                                      ({**gltg_headers, "X-Service-Tenant-ID": "other-tenant"}, 403)):
                response = client.post(gltg_url + "/v2/lead-time/simulate", json=body, headers=headers)
                check("negative identity HTTP " + str(expected), response.status_code == expected)
            wire_body = json.dumps(body).encode()
            with socket.create_connection(("127.0.0.1", ports[2]), timeout=5) as raw:
                raw.sendall(b"POST /v2/lead-time/simulate HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nConnection: close\r\nX-Service-Auth: invalid-\xff\r\nX-Service-Tenant-ID: " + tenant.encode() + b"\r\nContent-Length: " + str(len(wire_body)).encode() + b"\r\n\r\n" + wire_body)
                reply = b""
                while chunk := raw.recv(65536):
                    reply += chunk
            check("raw non-ASCII auth 401", b" 401 " in reply and b"CALLER_AUTH_INVALID" in reply)
            check("rejected identity creates no run", len(client.get(db_url + graph_path, headers=db_headers).json()["gltg_runs"]) == len(after["gltg_runs"]))
            for count in (0, 1, 2, 4):
                response = client.post(gltg_url + "/v2/paths/enumerate", json={"simulations": payloads[:count]}, headers=gltg_headers)
                check(f"provider-side {count} candidate paths", response.status_code == 200 and len(response.json()["paths"]) == count)

            # Execute the selected Aivan client's unmodified source over TCP.
            sys.path.insert(0, str(args.consumer_repo / "src"))
            try:
                consumer = importlib.import_module("aivan.integrations.gltg_client")
                os.environ["GLTG_SERVICE_AUTH_SECRET"] = inbound_secret
                consumed = consumer.GLTGClient(base_url=gltg_url).simulate_lead_time_v2(body)
                check("unmodified Aivan HTTP client", consumed.ok and consumed.data["quantiles"] == results[0]["quantiles"])
            finally:
                sys.path.remove(str(args.consumer_repo / "src"))
            stop(gltg); stop(provider)
            provider = start("giraffe_db.api.main:app", args.provider_repo, ports[1], provider_env)
            wait_ready(client, db_url + "/healthz")
            gltg = start("gltg.api.main:app", ROOT, ports[2], gltg_env)
            wait_ready(client, gltg_url + "/health")
            restarted = client.post(gltg_url + "/v2/lead-time/simulate", json=body, headers=gltg_headers).json()
            check("restart replay and API readback", restarted["quantiles"] == results[0]["quantiles"] and
                  restarted["persistence"]["giraffe_db_run_id"] == results[0]["persistence"]["giraffe_db_run_id"] and
                  restarted["persistence"]["readback_status"] == "verified")
            stop(provider)
            response = client.post(gltg_url + "/v2/lead-time/simulate", json=body, headers=gltg_headers)
            check("provider loss fails closed", response.status_code == 503 and response.json()["code"] == "DB_UNAVAILABLE")
            report["passed"] = True
    except Exception as exc:  # noqa: BLE001 -- Report any failed acceptance and always clean up.
        report["passed"] = False
        report["failure_type"] = type(exc).__name__
        # Assertion text is an owned check name, never a provider body or DSN.
        if isinstance(exc, AssertionError):
            report["failed_check"] = str(exc)
    finally:
        for process in reversed(processes):
            stop(process)
        for handle in handles:
            handle.close()
        report["cleanup"] = {"child_processes_stopped": all(p.poll() is not None for p in processes)}
        for attempt in range(20):
            try:
                temp.cleanup()
                break
            except PermissionError:
                if attempt == 19:
                    report["passed"] = False
                    report["failure_type"] = "TemporaryWorkspaceCleanupFailed"
                time.sleep(.1)
        report["cleanup"]["temporary_workspace_removed"] = not work.exists()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
