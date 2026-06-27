"""FastAPI application factory and ASGI entrypoint for the GLTG service.

Run locally:
    uvicorn gltg.api.main:app --host 0.0.0.0 --port 8090
"""

from __future__ import annotations

from fastapi import FastAPI

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
    app.include_router(router)
    return app


app = create_app()
