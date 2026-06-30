"""GLTG HTTP API routes."""

from __future__ import annotations

from fastapi import APIRouter

from ..behavioral.schemas import (
    GLTGPathV2,
    GLTGPathsEnumerateRequestV2,
    GLTGPathsEnumerateResponseV2,
    GLTGReforecastRequestV2,
    GLTGReforecastResponseV2,
    GLTGSimulationRequestV2,
    GLTGSimulationResponseV2,
)
from ..evaluator import orchestrator as gltg_evaluator
from ..version import __version__
from ..services import engine_adapter
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

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="gltg")


@router.get("/version", response_model=VersionResponse, tags=["meta"])
def version() -> VersionResponse:
    return VersionResponse(service="gltg", version=__version__, api_version="v1")


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
def simulate_lead_time_v2(req: GLTGSimulationRequestV2) -> GLTGSimulationResponseV2:
    return gltg_evaluator.evaluate(req)


@router.post(
    "/v2/paths/enumerate",
    response_model=GLTGPathsEnumerateResponseV2,
    tags=["paths-v2"],
)
def enumerate_paths_v2(req: GLTGPathsEnumerateRequestV2) -> GLTGPathsEnumerateResponseV2:
    paths: list[GLTGPathV2] = []
    warnings = []
    for sim_req in req.simulations:
        sim = gltg_evaluator.evaluate(sim_req)
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
def reforecast_v2(req: GLTGReforecastRequestV2) -> GLTGReforecastResponseV2:
    sim = gltg_evaluator.evaluate(req)
    return GLTGReforecastResponseV2(**sim.model_dump(), applied_events=req.events)
