"""Governed database entities per Blueprint §14."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import generate_record_pill, generate_uuidv7
from app.db.database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class MemoryRecord(Base):
    """Governed memory record (§6.2). Single source of truth for engineering decisions."""

    __tablename__ = "memory_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    pill: Mapped[str] = mapped_column(String(20), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    area: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)  # active, superseded, retracted
    confidence_band: Mapped[str] = mapped_column(String(20), default="high")  # high, medium, low
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    tentative: Mapped[bool] = mapped_column(Boolean, default=False)
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    hindsight_document_id: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    retain_state: Mapped[str] = mapped_column(String(30), default="pending", index=True)  # pending, retained, failed, retag_pending
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("memory_records.id"), nullable=True)
    superseded_by_id: Mapped[str | None] = mapped_column(ForeignKey("memory_records.id"), nullable=True)
    check_patterns_json: Mapped[str] = mapped_column(Text, default="[]")
    times_applied: Mapped[int] = mapped_column(Integer, default=0)
    times_violated: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    # Relationships
    evidence: Mapped[list[RecordEvidence]] = relationship("RecordEvidence", back_populates="record", cascade="all, delete-orphan")

    def __init__(self, **kw):
        super().__init__(**kw)
        if not self.id:
            self.id = generate_uuidv7()
        if not self.pill:
            self.pill = generate_record_pill(self.id)
        if not self.hindsight_document_id:
            self.hindsight_document_id = f"mem_{self.id}"


class RecordEvidence(Base):
    """Evidence citations and transcript quotes attached to a governed record."""

    __tablename__ = "record_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    record_id: Mapped[str] = mapped_column(ForeignKey("memory_records.id"), index=True, nullable=False)
    source_session_id: Mapped[str | None] = mapped_column(ForeignKey("agent_sessions.id"), nullable=True)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    speaker: Mapped[str] = mapped_column(String(50), default="human")
    turn_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    record: Mapped[MemoryRecord] = relationship("MemoryRecord", back_populates="evidence")


class SessionTurn(Base):
    """Turns captured within an agent or human-assisted coding session."""

    __tablename__ = "session_turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id"), index=True, nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # human, agent, tool
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class MemoryCandidate(Base):
    """Extracted decisions in the Inbox awaiting human review or automated qualification."""

    __tablename__ = "memory_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id"), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    area: Mapped[str | None] = mapped_column(String(100), nullable=True)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)  # pending, approved, rejected, filtered
    filter_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    relation: Mapped[str] = mapped_column(String(30), default="unrelated")  # extends, supersedes, conflicts, unrelated
    related_record_id: Mapped[str | None] = mapped_column(ForeignKey("memory_records.id"), nullable=True)
    confidence: Mapped[float] = mapped_column(default=0.8)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class TaskRun(Base):
    """Persisted record of an agent generation task (baseline or memory-aware)."""

    __tablename__ = "task_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("agent_sessions.id"), nullable=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)  # baseline, memory
    task: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    output_files_json: Mapped[str] = mapped_column(Text, default="[]")
    output_notes_json: Mapped[str] = mapped_column(Text, default="[]")
    followed_record_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    brief_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class CheckRun(Base):
    """Persisted memory compliance check result."""

    __tablename__ = "check_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"), nullable=True)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)  # pass, fail, warn, conflict, unavailable
    violations_json: Mapped[str] = mapped_column(Text, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    conflicts_json: Mapped[str] = mapped_column(Text, default="[]")
    recalled_record_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    checked_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ComparisonRun(Base):
    """Side-by-side comparison between baseline and memory-aware agent runs."""

    __tablename__ = "comparison_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="completed")  # pending, completed, failed
    stage: Mapped[str] = mapped_column(String(50), default="done")
    baseline_run_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"), nullable=True)
    memory_run_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"), nullable=True)
    baseline_check_id: Mapped[str | None] = mapped_column(ForeignKey("check_runs.id"), nullable=True)
    memory_check_id: Mapped[str | None] = mapped_column(ForeignKey("check_runs.id"), nullable=True)
    violations_baseline: Mapped[int] = mapped_column(Integer, default=0)
    violations_memory: Mapped[int] = mapped_column(Integer, default=0)
    violation_delta: Mapped[int] = mapped_column(Integer, default=0)
    applied_count: Mapped[int] = mapped_column(Integer, default=0)
    injected_tokens: Mapped[int] = mapped_column(Integer, default=0)
    fairness_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
