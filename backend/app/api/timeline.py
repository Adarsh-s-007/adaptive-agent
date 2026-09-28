"""Knowledge timeline: GET /projects/{pid}/timeline, newest first. Owner: P3."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MemoryEvent, MemoryRecord
from app.db.session import get_db
from app.schemas.memories import TimelineEvent

router = APIRouter(tags=["timeline"])

# Knowledge-changing events only; recall/check traffic stays out of the timeline.
TIMELINE_TYPES = ("RETAIN", "SUPERSEDE", "RETRACT", "RETAG", "MODEL_REFRESH")


@router.get("/projects/{project_id}/timeline", response_model=list[TimelineEvent])
async def timeline(
    project_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)], limit: int = 200
):
    rows = await db.execute(
        select(MemoryEvent, MemoryRecord.title)
        .outerjoin(MemoryRecord, MemoryRecord.id == MemoryEvent.record_id)
        .where(MemoryEvent.project_id == project_id, MemoryEvent.event_type.in_(TIMELINE_TYPES))
        .order_by(MemoryEvent.created_at.desc())
        .limit(min(limit, 500))
    )
    return [
        TimelineEvent(
            id=e.id,
            event_type=e.event_type,
            status=e.status,
            record_id=e.record_id,
            record_title=title,
            detail=e.detail,
            created_at=e.created_at,
        )
        for e, title in rows.all()
    ]
