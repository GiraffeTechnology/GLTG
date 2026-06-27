"""FastAPI application factory and ASGI entrypoint for the GLTG service.

Run locally:
    uvicorn gltg.api.main:app --host 0.0.0.0 --port 8090
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..errors import GLTGError
from ..version import __version__
from .routes import router


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

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "code": "INTERNAL_ERROR"},
        )

    app.include_router(router)
    return app


app = create_app()
