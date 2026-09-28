"""Request/response models for memory records and timeline. Owner: P3."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import MemoryRecordOut, MemoryType, RecordSource, StatedBy


class RecordCreate(BaseModel):
    type: MemoryType
    title: str = Field(min_length=3, max_length=80)
    statement: str = Field(min_length=20, max_length=400)
    rationale: str | None = Field(default=None, max_length=400)
    area: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9_-]+$")
    applies_to: list[str] = Field(default_factory=list, max_length=20)
    importance: int = Field(default=2, ge=1, le=3)
    confidence: float = Field(default=1.0, ge=0, le=1)
    stated_by: StatedBy = StatedBy.human
    decided_at: datetime | None = None
    source: RecordSource = RecordSource.manual
    evidence_quote: str | None = Field(default=None, max_length=2000)
    source_session_id: uuid.UUID | None = None
    check_patterns: dict | None = None
    approved_by: str = Field(default="manual", max_length=120)
    seed_key: str | None = Field(
        default=None, max_length=40, description="Stable key; makes seeding idempotent"
    )


class SupersedeRequest(RecordCreate):
    reviewer: str = Field(min_length=2, max_length=120)


class RetractRequest(BaseModel):
    reviewer: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=3, max_length=400)


class RecordDetail(MemoryRecordOut):
    retained_content: str
    version_chain: list[uuid.UUID]
    evidence: list[dict]


class SupersedeResult(BaseModel):
    record: MemoryRecordOut
    superseded_record: MemoryRecordOut


class TimelineEvent(BaseModel):
    id: uuid.UUID
    event_type: str
    status: str
    record_id: uuid.UUID | None
    record_title: str | None
    detail: dict
    created_at: datetime
