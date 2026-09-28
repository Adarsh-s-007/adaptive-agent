"""Memory Library and record lifecycle endpoints (blueprint 13.3). Owner: P3."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MemoryRecord, Project, RecordEvidence
from app.db.session import get_db
from app.schemas.common import MemoryRecordOut, MemoryType, RecordStatus
from app.schemas.memories import (
    RecordCreate,
    RecordDetail,
    RetractRequest,
    SupersedeRequest,
    SupersedeResult,
)
from app.services import memory_service as ms
from app.services.record_template import render_content

router = APIRouter(prefix="/projects/{project_id}/memories", tags=["memories"])
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=list[MemoryRecordOut])
async def list_memories(
    project_id: uuid.UUID,
    db: DB,
    type: MemoryType | None = None,
    area: str | None = None,
    status: RecordStatus | None = None,
    q: str | None = None,
):
    records = await ms.list_records(db, project_id, type_=type, area=area, status=status, q=q)
    counts = await ms.evidence_counts(db, [r.id for r in records])
    return [ms.to_out(r, counts.get(r.id, 1)) for r in records]


@router.post("", response_model=MemoryRecordOut, status_code=201)
async def create_memory(project_id: uuid.UUID, body: RecordCreate, db: DB):
    """Manual or seed record. Uses the same validation and retain path as approvals."""
    return ms.to_out(await ms.create_record(db, project_id, body))


@router.get("/{record_id}", response_model=RecordDetail)
async def get_memory(project_id: uuid.UUID, record_id: uuid.UUID, db: DB):
    record = await ms.get_record(db, project_id, record_id)
    project = await db.get(Project, project_id)
    replaces = (
        await db.get(MemoryRecord, record.supersedes_record_id)
        if record.supersedes_record_id
        else None
    )
    evidence_rows = list(
        await db.scalars(select(RecordEvidence).where(RecordEvidence.record_id == record.id))
    )
    evidence = (
        [{"session_id": record.source_session_id, "quote": record.evidence_quote}]
        if record.evidence_quote
        else []
    )
    evidence += [
        {"session_id": e.session_id, "quote": e.quote, "added_at": e.added_at}
        for e in evidence_rows
    ]
    return RecordDetail(
        **ms.to_out(record, 1 + len(evidence_rows)).model_dump(),
        retained_content=render_content(record, project.name if project else "", replaces),
        version_chain=await ms.version_chain(db, record),
        evidence=evidence,
    )


@router.post("/{record_id}/supersede", response_model=SupersedeResult)
async def supersede_memory(
    project_id: uuid.UUID, record_id: uuid.UUID, body: SupersedeRequest, db: DB
):
    data = RecordCreate.model_validate(body.model_dump(exclude={"reviewer"}))
    new, old = await ms.supersede(db, project_id, record_id, data, reviewer=body.reviewer)
    return SupersedeResult(record=ms.to_out(new), superseded_record=ms.to_out(old))


@router.post("/{record_id}/retract", response_model=MemoryRecordOut)
async def retract_memory(project_id: uuid.UUID, record_id: uuid.UUID, body: RetractRequest, db: DB):
    return ms.to_out(
        await ms.retract(db, project_id, record_id, reviewer=body.reviewer, reason=body.reason)
    )


@router.post("/{record_id}/retry", response_model=MemoryRecordOut)
async def retry_memory(project_id: uuid.UUID, record_id: uuid.UUID, db: DB):
    return ms.to_out(await ms.retry(db, project_id, record_id))
