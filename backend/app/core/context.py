"""Per-request context shared by middleware, error handlers and structured logs."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def set_request_id(value: str | None) -> None:
    _request_id.set(value)


def get_request_id() -> str:
    """Return the current request ID, or a fresh one outside a request."""
    return _request_id.get() or new_request_id()
