"""Wire models shared by services, routers and MCP tools."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    DECISION = "decision"
    SECURITY_CONSTRAINT = "security_constraint"
    CONVENTION = "convention"
    API_CONTRACT = "api_contract"
    INCIDENT = "incident"
    FAILED_APPROACH = "failed_approach"
    DEPLOYMENT = "deployment"
    PREFERENCE = "preference"


class RecordRef(BaseModel):
    id: str
    pill: str
    type: str
    title: str
    statement: str
    rationale: str | None = None
    area: str | None = None
    applies_to: list[str] = Field(default_factory=list)
    importance: int = 2
    status: str = "active"
    confidence_band: str = "high"
    decided_at: str | None = None
    tentative: bool = False
    review_due: bool = False
    retain_state: str | None = None


class AppliedRecord(BaseModel):
    record: RecordRef
    rank: int
    recall_rank: int | None = None
    score: float | None = None
    reason: str


class FilteredRecord(BaseModel):
    record: RecordRef
    recall_rank: int | None = None
    reason: str


class Observation(BaseModel):
    text: str
    record_ids: list[str] = Field(default_factory=list)


class BriefResult(BaseModel):
    # ok · empty · memory_unavailable · unfiltered · none_apply
    status: str
    message: str | None = None
    query: str
    recalled: list[RecordRef] = Field(default_factory=list)
    applied: list[AppliedRecord] = Field(default_factory=list)
    filtered: list[FilteredRecord] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    filter_mode: str = "llm"  # llm · heuristic · unfiltered · none
    recall_ms: int = 0
    filter_ms: int = 0
    recall_attempts: int = 0
    injected_tokens: int = 0
    all_records_tokens: int = 0
    active_records: int = 0
    memory_block: str = ""


class GeneratedFileOut(BaseModel):
    path: str
    language: str = "text"
    content: str = ""


class RunOutput(BaseModel):
    summary: str
    files: list[GeneratedFileOut] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    followed_record_ids: list[str] = Field(default_factory=list)


class TaskRunOut(BaseModel):
    id: str
    project_id: str
    session_id: str | None = None
    comparison_id: str | None = None
    repeat_index: int = 0
    mode: str
    task: str
    status: str = "ok"
    error: dict[str, Any] | None = None
    model: str | None = None
    output: RunOutput
    brief: BriefResult | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    injected_tokens: int = 0
    recall_ms: int = 0
    filter_ms: int = 0
    llm_ms: int = 0
    latency_ms: int = 0
    created_at: str


class Finding(BaseModel):
    record_id: str
    record_pill: str
    record_title: str = ""
    severity: str
    rule_statement: str
    excerpt: str
    explanation: str
    suggested_fix: str
    pattern_evidence: list[str] = Field(default_factory=list)
    tentative: bool = False


# Backwards-compatible alias.
ViolationOut = Finding


class ConflictOut(BaseModel):
    record_ids: list[str] = Field(default_factory=list)
    record_pills: list[str] = Field(default_factory=list)
    explanation: str = ""


class CheckResult(BaseModel):
    id: str | None = None
    verdict: str  # compliant · violations · unavailable
    message: str | None = None
    summary: str = ""
    judge_mode: str = "llm"  # llm · heuristic
    judge_model: str | None = None
    violations: list[Finding] = Field(default_factory=list)
    warnings: list[Finding] = Field(default_factory=list)
    conflicts: list[ConflictOut] = Field(default_factory=list)
    recalled_records: list[RecordRef] = Field(default_factory=list)
    dropped_findings: int = 0
    checked_tokens: int = 0
    latency_ms: int = 0


class CompareResult(BaseModel):
    id: str
    status: str
    stage: str
    task: str = ""
    repeats: int = 1
    baseline_run: TaskRunOut | None = None
    memory_run: TaskRunOut | None = None
    baseline_check: CheckResult | None = None
    memory_check: CheckResult | None = None
    baseline_runs: list[TaskRunOut] = Field(default_factory=list)
    memory_runs: list[TaskRunOut] = Field(default_factory=list)
    baseline_checks: list[CheckResult] = Field(default_factory=list)
    memory_checks: list[CheckResult] = Field(default_factory=list)
    violations_baseline: float = 0
    violations_memory: float = 0
    violation_delta: float = 0
    applied_count: int = 0
    injected_tokens: int = 0
    summary: dict[str, Any] = Field(default_factory=dict)
    fairness: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    created_at: str
