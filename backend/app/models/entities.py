import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    slug: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    tech_stack: Mapped[str | None] = mapped_column(Text, default="", nullable=True)
    areas_json: Mapped[str | None] = mapped_column(Text, default="[]", nullable=True)
    hindsight_bank_id: Mapped[str] = mapped_column(String(180), unique=True)
    # provisioning · ready · error
    bank_status: Mapped[str] = mapped_column(String(30), default="ready")
    bank_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    provisioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rulebook_mental_model_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rulebook_cache: Mapped[str | None] = mapped_column(Text, nullable=True)
    rulebook_cached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AgentSession(Base):
    """A coding-agent session: workspace chat, imported transcript, or legacy MCP call."""

    __tablename__ = "agent_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    agent_name: Mapped[str] = mapped_column(String(120))
    task: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    developer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    agent_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # workspace · import · seed · mcp · legacy
    source: Mapped[str | None] = mapped_column(String(20), default="legacy", nullable=True)
    # open · closed · extracted
    status: Mapped[str | None] = mapped_column(String(20), default="closed", nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_stats_json: Mapped[str | None] = mapped_column(Text, default="{}", nullable=True)
    turn_count: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MemoryEvent(Base):
    """Legacy MCP-era audit of retain/recall calls (kept for the MCP tools and their tests)."""

    __tablename__ = "memory_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("agent_sessions.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(20))
    source_text: Mapped[str] = mapped_column(Text)
    hindsight_memory_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DemoScenario(Base):
    __tablename__ = "demo_scenarios"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    task: Mapped[str] = mapped_column(Text)
    expected_memory_ids: Mapped[str] = mapped_column(Text, default="[]")


class DemoMemory(Base):
    """Local sample memory; never presented as Hindsight data."""

    __tablename__ = "demo_memories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    document_id: Mapped[str] = mapped_column(String(180), unique=True)
    content: Mapped[str] = mapped_column(Text)
    memory_type: Mapped[str] = mapped_column(String(60))
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    source_agent: Mapped[str] = mapped_column(String(120))
    session_id: Mapped[str | None] = mapped_column(ForeignKey("agent_sessions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AgentActivity(Base):
    """Visible audit of real MCP calls and explicitly labelled demo results."""

    __tablename__ = "agent_activity"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("agent_sessions.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(40))
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    origin: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
