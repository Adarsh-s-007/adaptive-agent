"""Request bodies for /api/v1. No request model accepts a bank ID (I3): extra fields are ignored."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class ProjectCreateBody(_Body):
    name: str = Field(..., min_length=2, max_length=150)
    description: str = Field(default="", max_length=2000)
    tech_stack: str = Field(default="", max_length=500)
    areas: list[str] = Field(default_factory=list, max_length=20)


class SessionCreateBody(_Body):
    title: str = Field(..., min_length=2, max_length=200)
    developer: str = Field(default="Developer", max_length=120)
    agent_label: str = Field(default="ProjectPulse agent", max_length=120)


class MessageBody(_Body):
    content: str = Field(..., min_length=2, max_length=8000)
    use_memory: bool = True
    file_paths: list[str] = Field(default_factory=list, max_length=10)


class ImportBody(_Body):
    title: str = Field(default="Imported session", min_length=2, max_length=200)
    developer: str = Field(default="Developer", max_length=120)
    agent_label: str = Field(default="Coding agent", max_length=120)
    occurred_at: datetime | None = None
    format: Literal["markdown", "jsonl", "plain"] | None = None
    text: str | None = Field(default=None, max_length=200_000)
    # Legacy field names.
    transcript: str | None = Field(default=None, max_length=200_000)
    format_hint: str | None = None
    extract: bool = False

    @model_validator(mode="after")
    def _text_required(self):
        if not (self.text or self.transcript):
            raise ValueError("text is required")
        if len((self.text or self.transcript or "").strip()) < 10:
            raise ValueError("transcript is too short")
        return self

    @property
    def body(self) -> str:
        return self.text or self.transcript or ""

    @property
    def fmt(self) -> str:
        return self.format or self.format_hint or "markdown"


class CloseBody(_Body):
    extract: bool = True


class RememberBody(_Body):
    title: str = Field(..., min_length=3, max_length=120)
    statement: str = Field(..., min_length=15, max_length=400)
    type: str = "decision"
    area: str | None = None
    rationale: str | None = Field(default=None, max_length=400)
    quote: str | None = Field(default=None, max_length=2000)
    reviewer: str = Field(default="Reviewer", max_length=120)


class ApproveBody(_Body):
    reviewer: str = Field(default="Reviewer", max_length=120)
    resolution: Literal["new", "supersede", "keep_both", "add_evidence"] | None = None
    target_record_id: str | None = None
    edits: dict | None = None


class RejectBody(_Body):
    reviewer: str = Field(default="Reviewer", max_length=120)
    reason: str = Field(default="Rejected by reviewer", max_length=400)


class ReviewBody(_Body):
    """Legacy combined review body."""

    resolution: str = "new"
    target_record_id: str | None = None
    edited_title: str | None = None
    edited_statement: str | None = None
    reviewer: str = "Reviewer"


class BulkApproveBody(_Body):
    reviewer: str = Field(default="Reviewer", max_length=120)


class RecordCreateBody(_Body):
    title: str = Field(..., min_length=3, max_length=255)
    statement: str = Field(..., min_length=15, max_length=2000)
    memory_type: str | None = None
    type: str | None = None
    rationale: str | None = Field(default=None, max_length=2000)
    area: str | None = None
    applies_to: list[str] = Field(default_factory=list, max_length=12)
    importance: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] = Field(default_factory=list, max_length=12)
    check_patterns: list[str] = Field(default_factory=list, max_length=12)
    evidence_quote: str | None = Field(default=None, max_length=2000)
    decided_at: datetime | None = None
    source: Literal["manual", "seed"] = "manual"
    reviewer: str = Field(default="Reviewer", max_length=120)

    @property
    def kind(self) -> str:
        return self.type or self.memory_type or "decision"

    @property
    def importance3(self) -> int | None:
        return min(3, self.importance) if self.importance else None


class SupersedeBody(_Body):
    title: str = Field(..., min_length=3, max_length=255)
    statement: str = Field(..., min_length=10, max_length=2000)
    rationale: str | None = None
    area: str | None = None
    type: str | None = None
    applies_to: list[str] | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    evidence_quote: str | None = None
    reviewer: str = Field(default="Reviewer", max_length=120)


class RetractBody(_Body):
    reason: str | None = Field(default=None, max_length=400)
    reviewer: str = Field(default="Reviewer", max_length=120)


class BriefBody(_Body):
    task: str = Field(..., min_length=3, max_length=8000)
    file_paths: list[str] = Field(default_factory=list, max_length=10)


class RunBody(_Body):
    task: str = Field(..., min_length=3, max_length=8000)
    mode: Literal["baseline", "memory"] = "memory"
    session_id: str | None = None
    file_paths: list[str] = Field(default_factory=list, max_length=10)


class CompareBody(_Body):
    task: str = Field(..., min_length=3, max_length=8000)
    repeats: int = Field(default=1, ge=1, le=3)


class CheckBody(_Body):
    content: str = Field(..., min_length=5, max_length=60_000)
    run_id: str | None = None


class AskBody(_Body):
    question: str = Field(..., min_length=3, max_length=2000)


class EvalBody(_Body):
    set: str = "default"


class SeedBody(_Body):
    project: Literal["apexcart", "ledgerlite"] = "apexcart"
    reset: bool = False


class DatasetBody(_Body):
    dataset: Literal["apexcart", "ledgerlite"] = "apexcart"


class OfflineBody(_Body):
    force_offline: bool
