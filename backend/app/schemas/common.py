"""Shared enums and record wire shapes (contracts C-2, C-3). Owner: P1."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class MemoryType(StrEnum):
    decision = "decision"
    security_constraint = "security_constraint"
    convention = "convention"
    api_contract = "api_contract"
    incident = "incident"
    failed_approach = "failed_approach"
    deployment = "deployment"
    preference = "preference"


class RecordStatus(StrEnum):
    active = "active"
    superseded = "superseded"
    retracted = "retracted"


class RetainState(StrEnum):
    pending = "pending"
    retained = "retained"
    failed = "failed"
    retag_pending = "retag_pending"


class Relation(StrEnum):
    new = "new"
    duplicate = "duplicate"
    refines = "refines"
    conflicts = "conflicts"
    supersedes = "supersedes"


class CandidateStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    auto_rejected = "auto_rejected"


class SessionStatus(StrEnum):
    open = "open"
    closed = "closed"
    extracted = "extracted"


class SessionSource(StrEnum):
    workspace = "workspace"
    import_ = "import"
    seed = "seed"


class TurnRole(StrEnum):
    human = "human"
    agent = "agent"
    tool = "tool"


class StatedBy(StrEnum):
    human = "human"
    agent = "agent"
    both = "both"


class RunMode(StrEnum):
    baseline = "baseline"
    memory = "memory"


class Verdict(StrEnum):
    compliant = "compliant"
    violations = "violations"
    unavailable = "unavailable"


class Severity(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class BankStatus(StrEnum):
    provisioning = "provisioning"
    ready = "ready"
    error = "error"


class RecordSource(StrEnum):
    extracted = "extracted"
    manual = "manual"
    seed = "seed"


class ConfidenceBand(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


def confidence_band(value: float) -> ConfidenceBand:
    if value >= 0.75:
        return ConfidenceBand.high
    if value >= 0.4:
        return ConfidenceBand.medium
    return ConfidenceBand.low


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class RecordRef(BaseModel):
    """Compact record used in briefs, checks, compare panes and pills."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pill: str
    type: MemoryType
    title: str
    statement: str
    area: str
    importance: int
    status: RecordStatus
    confidence_band: ConfidenceBand
    decided_at: datetime
    tentative: bool = False


class MemoryRecordOut(RecordRef):
    """Full record for the Library and Record drawer."""

    project_id: uuid.UUID
    rationale: str | None
    applies_to: list[str]
    confidence: float
    stated_by: StatedBy
    source_session_id: uuid.UUID | None
    evidence_quote: str | None
    evidence_turn_ids: list[int]
    supersedes_record_id: uuid.UUID | None
    superseded_by_record_id: uuid.UUID | None
    hindsight_document_id: str
    retain_state: RetainState
    source: RecordSource
    approved_by: str | None
    approved_at: datetime | None
    review_due_at: datetime | None
    evidence_count: int = 1
