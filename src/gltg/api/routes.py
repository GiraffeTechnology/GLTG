"""GLTG HTTP API routes."""

from __future__ import annotations

from fastapi import APIRouter

from ..version import __version__
from .. import services
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
    return services.estimate(req.order, req.suppliers, req.constraints)


@router.post(
    "/v1/paths/enumerate",
    response_model=PathEnumerateResponse,
    tags=["paths"],
)
def enumerate_paths(req: PathEnumerateRequest) -> PathEnumerateResponse:
    return services.enumerate_paths(req.order, req.suppliers, req.constraints)


@router.post(
    "/v1/reforecast",
    response_model=ReforecastResponse,
    tags=["reforecast"],
)
def reforecast(req: ReforecastRequest) -> ReforecastResponse:
    return services.reforecast(req.order, req.suppliers, req.events, req.constraints)
