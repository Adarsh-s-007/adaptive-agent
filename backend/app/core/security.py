"""Shared access token and admin guard (blueprint sections 12.5, 17). Owner: P1."""

import hmac

from fastapi import Header

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode


async def require_access_token(authorization: str | None = Header(default=None)) -> None:
    expected = get_settings().app_access_token
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), expected.encode()):
        raise AppError(ErrorCode.UNAUTHORIZED, "Missing or invalid access token.")


async def require_demo_mode() -> None:
    if not get_settings().demo_mode:
        raise AppError(ErrorCode.NOT_FOUND, "Admin routes are disabled.")
