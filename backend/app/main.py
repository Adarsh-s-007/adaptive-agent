"""ProjectPulse API: app factory, middleware, error envelope, health and background jobs."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

import app.db.governed_models
import app.models.entities
from app.api.routes import router as legacy_router
from app.api.v1 import v1_router
from app.config import get_settings
from app.core.context import new_request_id, set_request_id
from app.core.errors import AppError, AppErrorCode, error_envelope
from app.core.logging import configure_logging, get_logger
from app.db.database import engine, sync_schema
from app.services.hindsight_service import HindsightService

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger("api")

# Create/upgrade tables at import so every entry point (tests, MCP, uvicorn) is ready.
sync_schema()


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.jobs.retry_worker import RetryWorker
    from app.services.container import services

    worker = None
    if settings.enable_background_jobs:
        worker = RetryWorker(services().memory)
        worker.start()
    log.info("ProjectPulse API started", extra={"event": "startup"})
    yield
    if worker:
        await worker.stop()
    svc = services()
    await svc.hindsight.aclose()
    await svc.llm.aclose()


app = FastAPI(
    title="ProjectPulse API",
    version="2.0.0",
    description="Reviewed, persistent project memory for AI coding agents, powered by Hindsight.",
    lifespan=lifespan,
)


# ------------------------------------------------------------------ middleware
@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or new_request_id()
    set_request_id(request_id)
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > settings.max_body_bytes:
        body = error_envelope(AppErrorCode.PAYLOAD_TOO_LARGE, "Request body exceeds 1 MB.", request_id)
        return JSONResponse(status_code=413, content=body, headers={"X-Request-ID": request_id})
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled error", extra={"path": request.url.path})
        response = JSONResponse(
            status_code=500,
            content=error_envelope(AppErrorCode.INTERNAL_ERROR, "Unexpected server error.", request_id),
        )
    latency = int((time.perf_counter() - started) * 1000)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-ms"] = str(latency)
    if request.url.path.startswith("/api/"):
        log.info(
            "%s %s %s",
            request.method,
            request.url.path,
            response.status_code,
            extra={"latency_ms": latency, "status": response.status_code, "method": request.method, "path": request.url.path},
        )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Accept"],
    expose_headers=["X-Request-ID", "X-Response-Time-ms"],
)


# ------------------------------------------------------------------ errors
@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content=exc.to_envelope())


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    errors = [
        {"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg", "Invalid value")}
        for e in exc.errors()
    ]
    message = "; ".join(f"{e['field']}: {e['message']}" if e["field"] else e["message"] for e in errors[:4])
    body = error_envelope(AppErrorCode.VALIDATION_FAILED, message or "Invalid request.", details={"fields": errors})
    return JSONResponse(status_code=422, content=body)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_: Request, exc: StarletteHTTPException):
    code = {
        401: AppErrorCode.UNAUTHORIZED,
        404: AppErrorCode.NOT_FOUND,
        409: AppErrorCode.CONFLICT,
        422: AppErrorCode.VALIDATION_FAILED,
        503: AppErrorCode.SERVICE_UNAVAILABLE,
    }.get(exc.status_code, AppErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else AppErrorCode.VALIDATION_FAILED)
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return JSONResponse(status_code=exc.status_code, content=error_envelope(code, message))


# ------------------------------------------------------------------ routes
app.include_router(legacy_router)
app.include_router(v1_router, prefix="/api/v1")


async def _health_payload() -> dict:
    from app.services.container import services

    svc = services()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:  # noqa: BLE001
        db_status = "down"
    hindsight = await svc.hindsight.health()
    llm = await svc.llm.health()

    def level(state: str) -> str:
        return {"ok": "ok", "unconfigured": "down", "offline": "degraded", "degraded": "degraded"}.get(state, "down")

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "service": "ProjectPulse API",
        "version": app.version,
        "db": db_status,
        "hindsight": level(hindsight.get("status", "down")),
        "groq": level(llm.get("status", "down")),
        "details": {"hindsight": hindsight, "llm": llm},
        "hindsight_configured": settings.hindsight_configured,
        "groq_configured": settings.llm_configured,
        "demo_mode": settings.demo_mode,
    }


@app.get("/health", tags=["health"])
async def health():
    return await _health_payload()


@app.get("/api/v1/health", tags=["health"])
async def health_v1():
    return await _health_payload()


@app.get("/health/hindsight", tags=["health"])
async def hindsight_health():
    """Read-only Hindsight connectivity check for local setup verification."""
    return await HindsightService().probe()


logging.getLogger("httpx").setLevel(logging.WARNING)
