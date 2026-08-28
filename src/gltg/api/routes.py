"""GLTG HTTP API routes."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Header

from ..behavioral.schemas import (
    GLTGPathsEnumerateRequestV2,
    GLTGPathsEnumerateResponseV2,
    GLTGPathV2,
    GLTGReforecastRequestV2,
    GLTGReforecastResponseV2,
    GLTGSimulationRequestV2,
    GLTGSimulationResponseV2,
)
from ..evaluator.config import load_settings
from ..integrations.giraffe_db_client import GiraffeDBNotConfigured, client_from_env
from ..services import engine_adapter
from ..services.v2_pipeline import run_reforecast, run_simulation
from ..version import __version__
from .schemas import (
    HealthResponse,
    LeadTimeEstimateRequest,
    LeadTimeEstimateResponse,
    PathEnumerateRequest,
    PathEnumerateResponse,
    ReforecastRequest,
    ReforecastResponse,
    VersionResponse,
)
from .tenant_security import require_tenant_identity

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="gltg")


@router.get("/version", response_model=VersionResponse, tags=["meta"])
def version() -> VersionResponse:
    return VersionResponse(service="gltg", version=__version__, api_version="v1")


@router.get("/ready", tags=["meta"])
def ready() -> dict:
    """Dependency readiness without leaking secrets.

    ``/health`` means the process is alive; ``/ready`` reports whether the
    configured evaluation mode and optional giraffe-db dependency are usable.
    """
    settings = load_settings()
    try:
        client = client_from_env()
    except GiraffeDBNotConfigured:
        client = None
        giraffe_db_status = "auth_not_configured"
    else:
        giraffe_db_status = "not_configured"
    if client is not None:
        giraffe_db_status = "ok" if client.healthz() else "unreachable"
    evaluator_ready = settings.is_deterministic_mode or settings.evaluator_mode == "llm"
    ready_flag = evaluator_ready and giraffe_db_status not in {
        "unreachable",
        "auth_not_configured",
    }
    return {
        "ready": ready_flag,
        "evaluator_mode": settings.evaluator_mode,
        "giraffe_db": giraffe_db_status,
        "persistence_enabled": os.environ.get("GLTG_PERSIST_RUNS", "").strip().lower()
        in {"1", "true", "yes", "on"},
    }


@router.post(
    "/v1/lead-time/estimate",
    response_model=LeadTimeEstimateResponse,
    tags=["lead-time"],
)
def estimate_lead_time(req: LeadTimeEstimateRequest) -> LeadTimeEstimateResponse:
    return engine_adapter.estimate(req.order, req.suppliers, req.constraints)


@router.post(
    "/v1/paths/enumerate",
    response_model=PathEnumerateResponse,
    tags=["paths"],
)
def enumerate_paths(req: PathEnumerateRequest) -> PathEnumerateResponse:
    return engine_adapter.enumerate_paths(req.order, req.suppliers, req.constraints)


@router.post(
    "/v1/reforecast",
    response_model=ReforecastResponse,
    tags=["reforecast"],
)
def reforecast(req: ReforecastRequest) -> ReforecastResponse:
    return engine_adapter.reforecast(req.order, req.suppliers, req.events, req.constraints)


@router.post(
    "/v2/lead-time/simulate",
    response_model=GLTGSimulationResponseV2,
    tags=["lead-time-v2"],
)
def simulate_lead_time_v2(
    req: GLTGSimulationRequestV2,
    x_service_tenant_id: Annotated[
        str | None, Header(alias="X-Service-Tenant-ID")
    ] = None,
    x_service_auth: Annotated[str | None, Header(alias="X-Service-Auth")] = None,
) -> GLTGSimulationResponseV2:
    require_tenant_identity(x_service_tenant_id, x_service_auth, [req.tenant_id])
    return run_simulation(req)


@router.post(
    "/v2/paths/enumerate",
    response_model=GLTGPathsEnumerateResponseV2,
    tags=["paths-v2"],
)
def enumerate_paths_v2(
    req: GLTGPathsEnumerateRequestV2,
    x_service_tenant_id: Annotated[
        str | None, Header(alias="X-Service-Tenant-ID")
    ] = None,
    x_service_auth: Annotated[str | None, Header(alias="X-Service-Auth")] = None,
) -> GLTGPathsEnumerateResponseV2:
    require_tenant_identity(
        x_service_tenant_id,
        x_service_auth,
        [sim.tenant_id for sim in req.simulations],
    )
    paths: list[GLTGPathV2] = []
    warnings = []
    for sim_req in req.simulations:
        sim = run_simulation(sim_req, persist=False)
        paths.append(
            GLTGPathV2(
                path_id=f"v2:{sim_req.supplier.supplier_id or sim_req.request_id}",
                rank=0,
                supplier_id=sim_req.supplier.supplier_id,
                quantiles=sim.quantiles,
                risk=sim.risk,
                explanation_json=sim.explanation_json,
            )
        )
        warnings.extend(sim.warnings)
    paths.sort(key=lambda p: (p.risk.selected_confidence_days or p.quantiles.p80_days, p.path_id))
    for rank, path in enumerate(paths, start=1):
        path.rank = rank
    return GLTGPathsEnumerateResponseV2(ok=True, paths=paths, warnings=warnings)


@router.post(
    "/v2/reforecast",
    response_model=GLTGReforecastResponseV2,
    tags=["reforecast-v2"],
)
def reforecast_v2(
    req: GLTGReforecastRequestV2,
    x_service_tenant_id: Annotated[
        str | None, Header(alias="X-Service-Tenant-ID")
    ] = None,
    x_service_auth: Annotated[str | None, Header(alias="X-Service-Auth")] = None,
) -> GLTGReforecastResponseV2:
    require_tenant_identity(x_service_tenant_id, x_service_auth, [req.tenant_id])
    return run_reforecast(req)
