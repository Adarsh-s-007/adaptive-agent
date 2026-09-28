"""Error envelope and codes (blueprint section 13.2). Owner: P1.

Services raise AppError, never HTTPException. Every error response has the shape
{"error": {"code", "message", "request_id"}}.
"""

from __future__ import annotations

import logging
from enum import StrEnum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("projectpulse")


class ErrorCode(StrEnum):
    HINDSIGHT_UNAVAILABLE = "HINDSIGHT_UNAVAILABLE"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    LLM_OUTPUT_INVALID = "LLM_OUTPUT_INVALID"
    PROJECT_NOT_READY = "PROJECT_NOT_READY"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    CONFLICT = "CONFLICT"
    UNAUTHORIZED = "UNAUTHORIZED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


STATUS = {
    ErrorCode.HINDSIGHT_UNAVAILABLE: 503,
    ErrorCode.LLM_UNAVAILABLE: 503,
    ErrorCode.LLM_OUTPUT_INVALID: 502,
    ErrorCode.PROJECT_NOT_READY: 409,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.CONFLICT: 409,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.NOT_IMPLEMENTED: 501,
    ErrorCode.INTERNAL_ERROR: 500,
}


class AppError(Exception):
    def __init__(self, code: ErrorCode, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def not_implemented(owner: str) -> AppError:
    return AppError(ErrorCode.NOT_IMPLEMENTED, f"Not implemented yet (owner {owner}).")


def envelope(request: Request, code: str, message: str, details: dict | None = None) -> dict:
    body: dict = {
        "code": code,
        "message": message,
        "request_id": getattr(request.state, "request_id", None),
    }
    if details:
        body["details"] = details
    return {"error": body}


_HTTP_CODES = {401: ErrorCode.UNAUTHORIZED, 404: ErrorCode.NOT_FOUND, 409: ErrorCode.CONFLICT}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            envelope(request, exc.code, exc.message, exc.details), status_code=STATUS[exc.code]
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        message = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'][1:])}: {err['msg']}" for err in exc.errors()
        )
        return JSONResponse(
            envelope(request, ErrorCode.VALIDATION_FAILED, message or "Invalid request."),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, ErrorCode.VALIDATION_FAILED)
        if exc.status_code >= 500:
            code = ErrorCode.INTERNAL_ERROR
        return JSONResponse(envelope(request, code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", extra={"request_id": request.state.request_id})
        return JSONResponse(
            envelope(request, ErrorCode.INTERNAL_ERROR, "Unexpected server error."),
            status_code=500,
        )
