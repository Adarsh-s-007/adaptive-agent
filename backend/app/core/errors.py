"""Standard error envelope and application exceptions for ProjectPulse.

Every error leaves the API as::

    {"error": {"code": "...", "message": "...", "request_id": "..."}, "detail": "..."}

`detail` mirrors `message` so FastAPI-style clients (and the legacy dashboard routes)
keep working.
"""

from __future__ import annotations

from typing import Any

from app.core.context import get_request_id


class AppErrorCode:
    HINDSIGHT_UNAVAILABLE = "HINDSIGHT_UNAVAILABLE"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    LLM_OUTPUT_INVALID = "LLM_OUTPUT_INVALID"
    PROJECT_NOT_READY = "PROJECT_NOT_READY"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    CONFLICT = "CONFLICT"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    ISOLATION_VIOLATION = "ISOLATION_VIOLATION"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """Base application exception carrying an HTTP status and a stable error code."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        request_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.request_id = request_id or get_request_id()
        self.details = details or {}

    def to_envelope(self) -> dict[str, Any]:
        return error_envelope(self.code, self.message, self.request_id, self.details)


def error_envelope(
    code: str,
    message: str,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "error": {"code": code, "message": message, "request_id": request_id or get_request_id()},
        "detail": message,
    }
    if details:
        body["error"]["details"] = details
    return body


def not_found(what: str) -> AppError:
    return AppError(AppErrorCode.NOT_FOUND, f"{what} not found.", status_code=404)


def conflict(message: str) -> AppError:
    return AppError(AppErrorCode.CONFLICT, message, status_code=409)


def invalid(message: str, details: dict[str, Any] | None = None) -> AppError:
    return AppError(AppErrorCode.VALIDATION_FAILED, message, status_code=422, details=details)


def hindsight_unavailable(message: str = "Hindsight is unavailable.") -> AppError:
    return AppError(AppErrorCode.HINDSIGHT_UNAVAILABLE, message, status_code=503)


def llm_unavailable(message: str = "The LLM provider is unavailable.") -> AppError:
    return AppError(AppErrorCode.LLM_UNAVAILABLE, message, status_code=503)
