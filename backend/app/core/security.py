"""Authentication and authorization utilities for ProjectPulse API."""

from __future__ import annotations

import os
import secrets

from app.core.errors import AppError, AppErrorCode
from fastapi import Header, status


def get_access_token() -> str | None:
    return os.environ.get("APP_ACCESS_TOKEN", "").strip() or None


def verify_bearer_token(authorization: str | None = Header(default=None)) -> None:
    """Verify bearer token against APP_ACCESS_TOKEN if configured.

    Uses constant-time comparison to prevent timing attacks.
    """
    expected = get_access_token()
    if not expected:
        # Auth disabled / open access in development or test if APP_ACCESS_TOKEN is not set
        return

    if not authorization:
        raise AppError(
            code=AppErrorCode.UNAUTHORIZED,
            message="Missing Authorization header.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AppError(
            code=AppErrorCode.UNAUTHORIZED,
            message="Invalid Authorization header format. Expected 'Bearer <token>'.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    provided = parts[1]
    if not secrets.compare_digest(provided, expected):
        raise AppError(
            code=AppErrorCode.UNAUTHORIZED,
            message="Invalid or expired access token.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
