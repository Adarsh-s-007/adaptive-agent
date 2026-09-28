"""Common enums, types, and wire models for ProjectPulse (C-2, C-3, C-9)."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    ARCHITECTURE_DECISION = "architecture_decision"
    SECURITY_RULE = "security_rule"
    API_CONTRACT = "api_contract"
    INCIDENT_FIX = "incident_fix"
    CODING_CONVENTION = "coding_convention"
    DATA_MODEL = "data_model"
    PERFORMANCE_RULE = "performance_rule"
    OPERATIONAL_STANDARD = "operational_standard"


class RecordStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class RetainState(str, Enum):
    PENDING = "pending"
    RETAINED = "retained"
    FAILED = "failed"
    RETAG_PENDING = "retag_pending"


class Relation(str, Enum):
    EXTENDS = "extends"
    SUPERSEDES = "supersedes"
    CONFLICTS = "conflicts"
    UNRELATED = "unrelated"


class CandidateStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    FILTERED = "filtered"


class SessionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    EXTRACTED = "extracted"


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    CONFLICT = "conflict"


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ConfidenceBand(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class BankStatus(str, Enum):
    PROVISIONING = "provisioning"
    READY = "ready"
    ERROR = "error"


class RecordRef(BaseModel):
    id: str
    pill: str
    type: str
    title: str
    statement: str
    area: str | None = None
    importance: int = 3
    status: str = "active"
    confidence_band: str = "high"
    decided_at: str | None = None
    tentative: bool = False


class MemoryRecordOut(BaseModel):
    id: str
    pill: str
    project_id: str
    type: str
    title: str
    statement: str
    rationale: str | None = None
    area: str | None = None
    importance: int = 3
    status: str = "active"
    confidence_band: str = "high"
    decided_at: str
    tentative: bool = False
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    hindsight_document_id: str
    retain_state: str = "retained"
    evidence_count: int = 0
    review_due: bool = False
    superseded_by: str | None = None
    supersedes: str | None = None
    check_patterns: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str | None = None


class ViolationOut(BaseModel):
    record_id: str
    record_pill: str
    severity: str
    rule_statement: str
    excerpt: str
    explanation: str
    suggested_fix: str
    pattern_evidence: list[str] = Field(default_factory=list)


class CheckResult(BaseModel):
    verdict: str  # pass, fail, warn, conflict, unavailable
    violations: list[ViolationOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    recalled_records: list[RecordRef] = Field(default_factory=list)
    checked_tokens: int = 0
    latency_ms: int = 0


class AppliedRecord(BaseModel):
    record: RecordRef
    rank: int
    reason: str


class FilteredRecord(BaseModel):
    record: RecordRef
    reason: str


class BriefResult(BaseModel):
    status: str  # ok, empty, memory_unavailable, unfiltered
    query: str
    recalled: list[RecordRef] = Field(default_factory=list)
    applied: list[AppliedRecord] = Field(default_factory=list)
    filtered: list[FilteredRecord] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    recall_ms: int = 0
    filter_ms: int = 0
    injected_tokens: int = 0


class RunOutput(BaseModel):
    summary: str
    files: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    followed_record_ids: list[str] = Field(default_factory=list)


class TaskRunOut(BaseModel):
    id: str
    project_id: str
    mode: str  # baseline or memory
    task: str
    output: RunOutput
    brief: BriefResult | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int = 0
    created_at: str


class CompareResult(BaseModel):
    id: str
    status: str  # pending, completed, failed
    stage: str
    baseline_run: TaskRunOut | None = None
    memory_run: TaskRunOut | None = None
    baseline_check: CheckResult | None = None
    memory_check: CheckResult | None = None
    violations_baseline: int = 0
    violations_memory: int = 0
    violation_delta: int = 0  # baseline - memory (positive = improvement)
    applied_count: int = 0
    injected_tokens: int = 0
    fairness: dict[str, Any] = Field(default_factory=dict)
    created_at: str
