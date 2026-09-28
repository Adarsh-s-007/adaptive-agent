"""All ten tables from blueprint section 14. Owner: P1 (only P1 edits this file).

Write ownership (others go through the owner's service):
  projects -> P2 · agent_sessions, session_turns, memory_candidates -> P4
  memory_records, record_evidence -> P3 · task_runs -> P5
  check_runs, comparison_runs -> P6 · memory_events -> core.audit (everyone)

Types are portable (JSON instead of ARRAY) so unit tests can run on SQLite.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.session import Base

Json = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid7)


def created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


def project_fk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = pk()
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tech_stack: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    areas: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    hindsight_bank_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    bank_status: Mapped[str] = mapped_column(String(20), default="provisioning", nullable=False)
    rulebook_mental_model_id: Mapped[str | None] = mapped_column(String(120))
    rulebook_cache: Mapped[str | None] = mapped_column(Text)
    rulebook_cached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created()


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (Index("ix_sessions_project_started", "project_id", "started_at"),)
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = project_fk()
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    developer: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    agent_label: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="workspace", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    started_at: Mapped[datetime] = created()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskRun(Base):
    __tablename__ = "task_runs"
    __table_args__ = (
        Index("ix_runs_project_created", "project_id", "created_at"),
        Index("ix_runs_comparison", "comparison_id"),
    )
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = project_fk()
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agent_sessions.id", ondelete="SET NULL")
    )
    comparison_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("comparison_runs.id", ondelete="SET NULL")
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    recall_query: Mapped[str | None] = mapped_column(Text)
    recalled: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    applied: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    filtered: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    injected_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    recall_ms: Mapped[int | None] = mapped_column(Integer)
    filter_ms: Mapped[int | None] = mapped_column(Integer)
    llm_ms: Mapped[int | None] = mapped_column(Integer)
    output: Mapped[dict | None] = mapped_column(Json)
    followed_record_ids: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()


class SessionTurn(Base):
    __tablename__ = "session_turns"
    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_turn_session_seq"),)
    id: Mapped[uuid.UUID] = pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("task_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created()


class MemoryRecord(Base):
    __tablename__ = "memory_records"
    __table_args__ = (
        Index("ix_records_project_status", "project_id", "status"),
        Index("ix_records_project_type", "project_id", "type"),
        Index("ix_records_retain_state", "retain_state"),
    )
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = project_fk()
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    statement: Mapped[str] = mapped_column(String(400), nullable=False)
    rationale: Mapped[str | None] = mapped_column(String(400))
    area: Mapped[str] = mapped_column(String(40), nullable=False)
    applies_to: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    importance: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    stated_by: Mapped[str] = mapped_column(String(10), default="human", nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agent_sessions.id", ondelete="SET NULL")
    )
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    evidence_turn_ids: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    supersedes_record_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("memory_records.id", ondelete="SET NULL")
    )
    superseded_by_record_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("memory_records.id", ondelete="SET NULL")
    )
    hindsight_document_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    retain_state: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    retain_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    check_patterns: Mapped[dict | None] = mapped_column(Json)
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid
    )  # FK omitted: cycle with candidates
    approved_by: Mapped[str | None] = mapped_column(String(120))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created()


class MemoryCandidate(Base):
    __tablename__ = "memory_candidates"
    __table_args__ = (
        Index("ix_candidates_project_status", "project_id", "status"),
        Index("ix_candidates_session", "session_id"),
    )
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = project_fk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    area: Mapped[str] = mapped_column(String(40), nullable=False)
    applies_to: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    importance: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    stated_by: Mapped[str] = mapped_column(String(10), nullable=False)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_turn_ids: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    flags: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    relation: Mapped[str] = mapped_column(String(20), default="new", nullable=False)
    related_record_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("memory_records.id", ondelete="SET NULL")
    )
    relation_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    extractor_model: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = created()
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecordEvidence(Base):
    __tablename__ = "record_evidence"
    id: Mapped[uuid.UUID] = pk()
    record_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("memory_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agent_sessions.id", ondelete="SET NULL")
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    added_at: Mapped[datetime] = created()


class CheckRun(Base):
    __tablename__ = "check_runs"
    __table_args__ = (Index("ix_checks_project_created", "project_id", "created_at"),)
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = project_fk()
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("task_runs.id", ondelete="CASCADE"), index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    violations: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    warnings: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    conflicts: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    recalled_record_ids: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    judge_model: Mapped[str | None] = mapped_column(String(80))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created()


class ComparisonRun(Base):
    __tablename__ = "comparison_runs"
    __table_args__ = (Index("ix_comparisons_project_created", "project_id", "created_at"),)
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = project_fk()
    task: Mapped[str] = mapped_column(Text, nullable=False)
    repeats: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    baseline_run_ids: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    memory_run_ids: Mapped[list] = mapped_column(Json, default=list, nullable=False)
    summary: Mapped[dict | None] = mapped_column(Json)
    created_at: Mapped[datetime] = created()


class MemoryEvent(Base):
    __tablename__ = "memory_events"
    __table_args__ = (
        Index("ix_events_project_created", "project_id", "created_at"),
        Index("ix_events_type", "event_type"),
    )
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = project_fk()
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(10), default="ok", nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict] = mapped_column(Json, default=dict, nullable=False)
    created_at: Mapped[datetime] = created()
