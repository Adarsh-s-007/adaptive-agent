"""Small in-process sliding-window rate limiter for LLM-backed routes (Blueprint §17)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request

from app.config import get_settings
from app.core.errors import AppError, AppErrorCode


class SlidingWindowLimiter:
    def __init__(self, window_seconds: float = 60.0) -> None:
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str, limit: int) -> tuple[bool, float]:
        """Record one hit. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= limit:
                return False, max(0.0, self.window - (now - bucket[0]))
            bucket.append(now)
            return True, 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def llm_rate_limit(request: Request) -> None:
    """FastAPI dependency: at most N LLM-backed calls per minute per client IP."""
    limit = get_settings().llm_rate_limit_per_minute
    if limit <= 0:
        return
    client = request.client.host if request.client else "unknown"
    allowed, retry_after = limiter.hit(client, limit)
    if not allowed:
        raise AppError(
            code=AppErrorCode.RATE_LIMITED,
            message=f"Too many model-backed requests. Retry in {int(retry_after) + 1}s.",
            status_code=429,
            details={"retry_after_seconds": int(retry_after) + 1},
        )
