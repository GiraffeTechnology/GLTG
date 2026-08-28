"""FastAPI application factory and ASGI entrypoint for the GLTG service.

Run locally:
    uvicorn gltg.api.main:app --host 0.0.0.0 --port 8090
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..errors import GLTGError
from ..services.v2_pipeline import EvidenceAuthError, EvidenceUnavailableError
from ..version import __version__
from .routes import router
from .tenant_security import InboundIdentityError


def create_app() -> FastAPI:
    app = FastAPI(
        title="GLTG -- Giraffe Lead-Time Graph",
        description=(
            "Standalone lead-time, path-enumeration, and reforecasting service. "
            "Source of truth for all GLTG calculations consumed by giraffe-agent, "
            "abcdYi, and aivan."
        ),
        version=__version__,
    )

    # Unified error contract (DEFECT-05). Domain errors are client-actionable
    # (422); anything unexpected is a structured 500 rather than a bare HTML page.
    @app.exception_handler(GLTGError)
    async def _gltg_error_handler(request: Request, exc: GLTGError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": str(exc), "code": type(exc).__name__},
        )

    # giraffe-db evidence failures are explicit, never silent: an unreachable
    # evidence service is a 503 DB_UNAVAILABLE; rejected service auth/tenant
    # fails closed as a 502 EVIDENCE_AUTH_FAILED.
    @app.exception_handler(EvidenceUnavailableError)
    async def _evidence_unavailable_handler(
        request: Request, exc: EvidenceUnavailableError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"error": str(exc), "code": "DB_UNAVAILABLE"},
        )

    @app.exception_handler(EvidenceAuthError)
    async def _evidence_auth_handler(request: Request, exc: EvidenceAuthError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"error": str(exc), "code": "EVIDENCE_AUTH_FAILED"},
        )

    # Request-validation failures (DEFECT-API-01): FastAPI's default
    # ``{"detail": [...]}`` body is reshaped into the same
    # ``{"error": ..., "code": ...}`` envelope as domain errors so every error
    # response is structurally consistent. 422 remains the correct HTTP status.
    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": str(exc.errors()), "code": "VALIDATION_ERROR"},
        )

    @app.exception_handler(InboundIdentityError)
    async def _inbound_identity_handler(
        request: Request, exc: InboundIdentityError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "code": exc.code},
        )

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "code": "INTERNAL_ERROR"},
        )

    app.include_router(router)
    return app


app = create_app()
