import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
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
    description: Mapped[str] = mapped_column(Text, default="")
    hindsight_bank_id: Mapped[str] = mapped_column(String(180), unique=True)
    bank_status: Mapped[str] = mapped_column(String(30), default="ready")  # provisioning, ready, error
    rulebook_cache: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    agent_name: Mapped[str] = mapped_column(String(120))
    task: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MemoryEvent(Base):
    __tablename__ = "memory_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_sessions.id"), nullable=True
    )
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
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_sessions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AgentActivity(Base):
    """Visible audit of real MCP calls and explicitly labelled demo results."""

    __tablename__ = "agent_activity"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_sessions.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    origin: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
