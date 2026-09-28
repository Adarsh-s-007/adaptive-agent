"""The only writer of memory_events. Everyone calls record_event(). Owner: P1."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MemoryEvent


async def record_event(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    event_type: str,
    status: str = "ok",
    latency_ms: int | None = None,
    record_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    detail: dict | None = None,
) -> MemoryEvent:
    """Adds the event to the session; the caller commits with its own unit of work."""
    event = MemoryEvent(
        project_id=project_id,
        event_type=event_type,
        status=status,
        latency_ms=latency_ms,
        record_id=record_id,
        run_id=run_id,
        detail=detail or {},
    )
    db.add(event)
    await db.flush()
    return event
