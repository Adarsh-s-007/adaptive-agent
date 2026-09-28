"""Database audit events shared by the API and MCP server."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.entities import AgentActivity, AgentSession, MemoryEvent, Project


class AuditEventService:
    @staticmethod
    def session(
        db: Session, project: Project, agent_name: str, task: str
    ) -> AgentSession:
        session = AgentSession(project_id=project.id, agent_name=agent_name, task=task)
        db.add(session)
        db.flush()
        return session

    @staticmethod
    def activity(
        db: Session,
        project: Project,
        session: AgentSession | None,
        kind: str,
        summary: str,
        origin: str,
        *,
        tool_name: str | None = None,
        evidence: list[object] | None = None,
    ) -> AgentActivity:
        entry = AgentActivity(
            project_id=project.id,
            session_id=session.id if session else None,
            kind=kind,
            tool_name=tool_name,
            summary=summary,
            origin=origin,
            evidence_json=json.dumps(evidence or []),
        )
        db.add(entry)
        db.flush()
        return entry

    @staticmethod
    def memory_event(
        db: Session,
        project: Project,
        session: AgentSession | None,
        event_type: str,
        source_text: str,
        reference: object,
    ) -> MemoryEvent:
        event = MemoryEvent(
            project_id=project.id,
            session_id=session.id if session else None,
            event_type=event_type,
            source_text=source_text,
            hindsight_memory_reference=json.dumps(reference),
        )
        db.add(event)
        db.flush()
        return event
