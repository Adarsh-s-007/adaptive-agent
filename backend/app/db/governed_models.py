"""Governed database entities (Blueprint §14).

PostgreSQL is the system of governance: who approved what, lifecycle status, runs,
checks and the audit trail. It never stores embeddings and never serves agent-facing
retrieval; Hindsight owns all searchable memory.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import generate_record_pill, generate_uuidv7
from app.db.database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class MemoryRecord(Base):
    """An approved, immutable engineering record (§6.2). Edits create superseding versions."""

    __tablename__ = "memory_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    pill: Mapped[str] = mapped_column(String(20), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    area: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    applies_to_json: Mapped[str | None] = mapped_column(Text, default="[]", nullable=True)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    # active · superseded · retracted
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    confidence: Mapped[float | None] = mapped_column(Float, default=1.0, nullable=True)
    confidence_band: Mapped[str] = mapped_column(String(20), default="high")
    stated_by: Mapped[str | None] = mapped_column(String(20), default="human", nullable=True)
    # extracted · manual · seed
    source: Mapped[str | None] = mapped_column(String(20), default="manual", nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    tentative: Mapped[bool] = mapped_column(Boolean, default=False)
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    hindsight_document_id: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    retained_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pending · retained · failed · retag_pending
    retain_state: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("memory_records.id"), nullable=True)
    superseded_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("memory_records.id"), nullable=True
    )
    candidate_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retract_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    check_patterns_json: Mapped[str] = mapped_column(Text, default="[]")
    times_applied: Mapped[int] = mapped_column(Integer, default=0)
    times_violated: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    evidence: Mapped[list[RecordEvidence]] = relationship(
        "RecordEvidence",
        back_populates="record",
        cascade="all, delete-orphan",
        order_by="RecordEvidence.created_at",
    )

    def __init__(self, **kw):
        super().__init__(**kw)
        if not self.id:
            self.id = generate_uuidv7()
        if not self.pill:
            self.pill = generate_record_pill(self.id)
        if not self.hindsight_document_id:
            self.hindsight_document_id = f"mem_{self.id}"


class RecordEvidence(Base):
    """Evidence quotes backing a record; duplicates from later sessions append here."""

    __tablename__ = "record_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    record_id: Mapped[str] = mapped_column(
        ForeignKey("memory_records.id"), index=True, nullable=False
    )
    source_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_sessions.id"), nullable=True
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    speaker: Mapped[str] = mapped_column(String(50), default="human")
    turn_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    record: Mapped[MemoryRecord] = relationship("MemoryRecord", back_populates="evidence")


class SessionTurn(Base):
    """One turn of a coding session (human, agent or tool)."""

    __tablename__ = "session_turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("agent_sessions.id"), index=True, nullable=False
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # human · agent · tool
    speaker: Mapped[str | None] = mapped_column(String(120), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, default="{}", nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class MemoryCandidate(Base):
    """An extracted candidate awaiting human review in the Inbox (§5, §14)."""

    __tablename__ = "memory_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("agent_sessions.id"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    area: Mapped[str | None] = mapped_column(String(100), nullable=True)
    applies_to_json: Mapped[str | None] = mapped_column(Text, default="[]", nullable=True)
    importance: Mapped[int | None] = mapped_column(Integer, default=2, nullable=True)
    stated_by: Mapped[str | None] = mapped_column(String(20), default="human", nullable=True)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_turn_ids_json: Mapped[str | None] = mapped_column(Text, default="[]", nullable=True)
    # pending · approved · rejected · auto_rejected
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    filter_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # new · duplicate · refines · conflicts · supersedes
    relation: Mapped[str] = mapped_column(String(30), default="new")
    related_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("memory_records.id"), nullable=True
    )
    relation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(default=0.8)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    flags_json: Mapped[str | None] = mapped_column(Text, default="[]", nullable=True)
    extractor_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class TaskRun(Base):
    """One generation run (baseline or memory-aware), with its frozen recall snapshot."""

    __tablename__ = "task_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("agent_sessions.id"), nullable=True)
    comparison_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    repeat_index: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)  # baseline · memory
    task: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str | None] = mapped_column(String(20), default="ok", nullable=True)
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, default=0.0, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    output_files_json: Mapped[str] = mapped_column(Text, default="[]")
    output_notes_json: Mapped[str] = mapped_column(Text, default="[]")
    followed_record_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    brief_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    injected_tokens: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    recall_ms: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    filter_ms: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    llm_ms: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class CheckRun(Base):
    """A Memory Check verdict (compliant · violations · unavailable)."""

    __tablename__ = "check_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    judge_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    violations_json: Mapped[str] = mapped_column(Text, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    conflicts_json: Mapped[str] = mapped_column(Text, default="[]")
    recalled_record_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    checked_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ComparisonRun(Base):
    """Compare Mode: the same task with and without memory, both checked blind (§11)."""

    __tablename__ = "comparison_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    repeats: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="completed")  # running · completed · failed
    stage: Mapped[str] = mapped_column(String(50), default="done")
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    baseline_run_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"), nullable=True)
    memory_run_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"), nullable=True)
    baseline_check_id: Mapped[str | None] = mapped_column(ForeignKey("check_runs.id"), nullable=True)
    memory_check_id: Mapped[str | None] = mapped_column(ForeignKey("check_runs.id"), nullable=True)
    baseline_run_ids_json: Mapped[str | None] = mapped_column(Text, default="[]", nullable=True)
    memory_run_ids_json: Mapped[str | None] = mapped_column(Text, default="[]", nullable=True)
    violations_baseline: Mapped[int] = mapped_column(Integer, default=0)
    violations_memory: Mapped[int] = mapped_column(Integer, default=0)
    violation_delta: Mapped[int] = mapped_column(Integer, default=0)
    applied_count: Mapped[int] = mapped_column(Integer, default=0)
    injected_tokens: Mapped[int] = mapped_column(Integer, default=0)
    summary_json: Mapped[str | None] = mapped_column(Text, default="{}", nullable=True)
    fairness_json: Mapped[str] = mapped_column(Text, default="{}")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class OutboxMessage(Base):
    """Legacy explicit outbox rows. New writes use `memory_records.retain_state` as the outbox."""

    __tablename__ = "outbox_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    record_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    operation: Mapped[str] = mapped_column(String(30), nullable=False)  # retain, retag, delete
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


class AuditEvent(Base):
    """Every Hindsight/LLM call and governance action, with latency (Blueprint `memory_events`)."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # RETAIN · RECALL · REFLECT · RETAG · SUPERSEDE · RETRACT · EXTRACT · APPROVE · REJECT
    # MODEL_REFRESH · PROVISION · CHECK · GENERATE · ISOLATION_VIOLATION_BLOCKED …
    event_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="ok")  # ok · error
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)


class RulebookSnapshot(Base):
    """Point-in-time copies of the Rulebook so "What changed" works even offline."""

    __tablename__ = "rulebook_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="mental_model")
    trigger: Mapped[str | None] = mapped_column(String(60), nullable=True)
    active_record_count: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class EvalRun(Base):
    """A run of the labelled evaluation set (Blueprint §20, §25.4)."""

    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuidv7)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    set_name: Mapped[str] = mapped_column(String(60), default="default")
    status: Mapped[str] = mapped_column(String(20), default="completed")
    precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    forbidden_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    models_json: Mapped[str] = mapped_column(Text, default="{}")
    results_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
