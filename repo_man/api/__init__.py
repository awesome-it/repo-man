"""Optional REST API (FastAPI) under /api/v1."""

from __future__ import annotations

from starlette.requests import Request

from fastapi import FastAPI, HTTPException

from repo_man.api.models import ErrorResponse
from repo_man.api.routes import legacy_router, router as v1_router
from repo_man.metrics import http_requests_total
from repo_man.storage.base import StorageBackend


def create_api_app(storage: StorageBackend) -> FastAPI:
    """Create the FastAPI application for /api/v1 (publish, health)."""
    app = FastAPI(title="repo-man API", version="1.0")
    app.state.storage = storage

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        from fastapi.responses import JSONResponse
        body = ErrorResponse(error=str(exc.detail))
        return JSONResponse(
            status_code=exc.status_code,
            content=body.model_dump(),
        )

    @app.middleware("http")
    async def record_request_metrics(request: Request, call_next):
        response = await call_next(request)
        path_prefix = request.url.path
        http_requests_total.labels(
            method=request.method,
            path_prefix=path_prefix,
            status=str(response.status_code),
        ).inc()
        return response

    app.include_router(v1_router, prefix="/api/v1")
    app.include_router(legacy_router)  # POST /api/publish (deprecated)
    return app
