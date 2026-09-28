"""Brief request/response (contract C-9). Owner: P5."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.common import RecordRef


class BriefStatus(StrEnum):
    ok = "ok"
    empty = "empty"  # no active records, or none apply
    unfiltered = "unfiltered"  # applicability call failed; top 3 by rank used
    memory_unavailable = "memory_unavailable"


class BriefRequest(BaseModel):
    task: str = Field(min_length=3, max_length=8000)
    file_paths: list[str] = Field(default_factory=list, max_length=20)


class RecalledItem(BaseModel):
    record: RecordRef
    rank: int
    score: float | None = None


class AppliedItem(RecalledItem):
    reason: str


class Brief(BaseModel):
    status: BriefStatus
    query: str
    recalled: list[RecalledItem] = Field(default_factory=list)
    applied: list[AppliedItem] = Field(default_factory=list)
    filtered: list[AppliedItem] = Field(default_factory=list)
    recall_ms: int | None = None
    filter_ms: int | None = None
    injected_tokens: int = 0
    message: str | None = None
