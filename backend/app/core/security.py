"""Shared-token access control for the deployed API (Blueprint §12.5, §17)."""

from __future__ import annotations

import secrets

from fastapi import Header, status

from app.config import get_settings
from app.core.errors import AppError, AppErrorCode


def get_access_token() -> str | None:
    return (get_settings().app_access_token or "").strip() or None


def verify_bearer_token(authorization: str | None = Header(default=None)) -> None:
    """Require `Authorization: Bearer <APP_ACCESS_TOKEN>` when a token is configured.

    Local development runs open when APP_ACCESS_TOKEN is empty. The comparison is
    constant-time to avoid leaking the token through timing.
    """
    expected = get_access_token()
    if not expected:
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

    if not secrets.compare_digest(parts[1].encode(), expected.encode()):
        raise AppError(
            code=AppErrorCode.UNAUTHORIZED,
            message="Invalid access token.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


def require_demo_mode() -> None:
    """Admin routes exist only on demo deployments (DEMO_MODE=true)."""
    if not get_settings().demo_mode:
        raise AppError(
            code=AppErrorCode.FORBIDDEN,
            message="Admin endpoints are disabled (DEMO_MODE is off).",
            status_code=status.HTTP_403_FORBIDDEN,
        )
