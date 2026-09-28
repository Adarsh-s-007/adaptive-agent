"""Standard error envelope and application exceptions for ProjectPulse."""

from __future__ import annotations

import uuid
from typing import Any


class AppErrorCode:
    HINDSIGHT_UNAVAILABLE = "HINDSIGHT_UNAVAILABLE"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    LLM_OUTPUT_INVALID = "LLM_OUTPUT_INVALID"
    PROJECT_NOT_READY = "PROJECT_NOT_READY"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    CONFLICT = "CONFLICT"
    UNAUTHORIZED = "UNAUTHORIZED"
    ISOLATION_VIOLATION = "ISOLATION_VIOLATION"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """Base application exception following the blueprint contract C-1.
    
    Format: {"error": {"code": "...", "message": "...", "request_id": "..."}}
    """

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
        self.request_id = request_id or str(uuid.uuid4())
        self.details = details or {}

    def to_envelope(self) -> dict[str, Any]:
        envelope: dict[str, Any] = {
            "error": {
                "code": self.code,
                "message": self.message,
                "request_id": self.request_id,
            }
        }
        if self.details:
            envelope["error"]["details"] = self.details
        return envelope
