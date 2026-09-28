"""Project-scoped memory orchestration for MCP tools and dashboard API."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import AgentSession, DemoMemory, Project
from app.services.audit_event_service import AuditEventService
from app.services.hindsight_service import HindsightService

MEMORY_TYPES = (
    "architecture_decision",
    "security_rule",
    "api_contract",
    "incident_fix",
    "coding_convention",
)
LEGACY_TYPES = {
    "architecture decision": "architecture_decision",
    "coding convention": "coding_convention",
    "bug fix": "incident_fix",
    "failed approach": "incident_fix",
    "feature progress": "architecture_decision",
}
STOP_WORDS = {
    "the",
    "and",
    "for",
    "this",
    "that",
    "with",
    "from",
    "into",
    "your",
    "project",
    "implement",
    "build",
    "make",
    "work",
    "flow",
    "using",
    "should",
    "must",
    "use",
    "not",
    "agent",
    "code",
    "new",
    "app",
}
SECRET_PATTERN = re.compile(
    r"(?:hsk_|gsk_|sk-[A-Za-z0-9]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?:password|api[_-]?key)\s*[:=]\s*\S+)",
    re.IGNORECASE,
)


def project_or_404(db: Session, project_id: str) -> Project:
    try:
        uuid.UUID(project_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "project_id must be a UUID.") from exc
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found.")
    return project


def demo_mode(project: Project) -> bool:
    return project.hindsight_bank_id.startswith("demo-")


def memory_dto(memory: DemoMemory) -> dict:
    return {
        "id": memory.id,
        "text": memory.content,
        "type": memory.memory_type,
        "memory_type": memory.memory_type,
        "tags": json.loads(memory.tags_json),
        "metadata": {
            "memory_type": memory.memory_type,
            "source_agent": memory.source_agent,
            "session_id": memory.session_id or "",
        },
        "source_agent": memory.source_agent,
        "session_id": memory.session_id,
        "document_id": memory.document_id,
        "timestamp": memory.created_at.isoformat(),
        "source_text": memory.content,
        "origin": "demo",
        "why_relevant": None,
    }


def relevance_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in STOP_WORDS
    }


class ProjectMemoryService:
    def __init__(self, hindsight: HindsightService | None = None) -> None:
        self.hindsight = hindsight or HindsightService()
        self.audit = AuditEventService()
        self.settings = get_settings()

    def _session(
        self,
        db: Session,
        project: Project,
        source_agent: str,
        session_id: str | None,
        task: str,
    ) -> AgentSession:
        if session_id:
            session = db.get(AgentSession, session_id)
            if not session or session.project_id != project.id:
                raise HTTPException(422, "session_id does not belong to this project.")
            return session
        return self.audit.session(db, project, source_agent, task)

    @staticmethod
    def _tags(project: Project, tags: list[str]) -> list[str]:
        if len(tags) > 12:
            raise HTTPException(422, "At most 12 tags are allowed.")
        cleaned = []
        for tag in tags:
            tag = tag.strip()
            if not tag or len(tag) > 60 or tag.startswith("project:"):
                raise HTTPException(422, "Invalid tag.")
            if tag not in cleaned:
                cleaned.append(tag)
        return [f"project:{project.id}", *cleaned]

    async def retain(
        self,
        db: Session,
        project_id: str,
        content: str,
        memory_type: str,
        tags: list[str] | None = None,
        source_agent: str = "Coding agent",
        session_id: str | None = None,
        document_id: str | None = None,
        tool_name: str = "projectpulse.retain_project_memory",
    ) -> dict:
        project = project_or_404(db, project_id)
        content = content.strip()
        source_agent = source_agent.strip()
        memory_type = LEGACY_TYPES.get(memory_type, memory_type)
        if memory_type not in MEMORY_TYPES:
            raise HTTPException(422, "Unsupported memory_type.")
        if not 12 <= len(content) <= 12000 or not 2 <= len(source_agent) <= 120:
            raise HTTPException(422, "Invalid memory content or source agent.")
        if SECRET_PATTERN.search(content):
            raise HTTPException(422, "Do not retain secrets or credentials.")
        tags = self._tags(project, tags or [])
        document_id = document_id or f"memory-{uuid.uuid4()}"
        existing = (
            db.scalar(select(DemoMemory).where(DemoMemory.document_id == document_id))
            if demo_mode(project)
            else None
        )
        if existing:
            return {
                "memory": memory_dto(existing),
                "origin": "demo",
                "already_exists": True,
            }

        session = self._session(
            db, project, source_agent, session_id, "Retain project learning"
        )
        origin = "demo" if demo_mode(project) else "hindsight"
        if origin == "hindsight":
            response = await self.hindsight.retain(
                project.hindsight_bank_id,
                content=content,
                document_id=document_id,
                metadata={
                    "project_id": project.id,
                    "memory_type": memory_type,
                    "source_agent": source_agent,
                    "session_id": session.id,
                },
                tags=tags,
            )
            if response.get("success") is False:
                raise HTTPException(502, "Hindsight did not confirm Retain.")
            item = {
                "id": document_id,
                "text": content,
                "type": memory_type,
                "memory_type": memory_type,
                "tags": tags,
                "metadata": {
                    "memory_type": memory_type,
                    "source_agent": source_agent,
                    "session_id": session.id,
                },
                "source_agent": source_agent,
                "session_id": session.id,
                "document_id": document_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "origin": origin,
            }
        else:
            memory = DemoMemory(
                project_id=project.id,
                document_id=document_id,
                content=content,
                memory_type=memory_type,
                tags_json=json.dumps(tags),
                source_agent=source_agent,
                session_id=session.id,
            )
            db.add(memory)
            db.flush()
            item = memory_dto(memory)

        event = self.audit.memory_event(
            db,
            project,
            session,
            "retained",
            f"Memory type: {memory_type}\nSource agent: {source_agent}\n"
            f"Project: {project.name}\nDecision / learning: {content}",
            {"document_id": document_id, "origin": origin, "tags": tags},
        )
        self.audit.activity(
            db,
            project,
            session,
            "tool_call",
            content,
            origin,
            tool_name=tool_name,
            evidence=[item],
        )
        db.commit()
        db.refresh(event)
        return {
            "memory": item,
            "event_id": event.id,
            "session_id": session.id,
            "origin": origin,
            "mode_label": "Demo mode - local sample memory"
            if origin == "demo"
            else "Hindsight connected",
        }

    async def recall(
        self,
        db: Session,
        project_id: str,
        task_description: str,
        top_k: int = 5,
        source_agent: str = "Fresh coding agent",
        session_id: str | None = None,
        tool_name: str = "projectpulse.recall_project_memory",
    ) -> dict:
        project = project_or_404(db, project_id)
        task_description = task_description.strip()
        if not 3 <= len(task_description) <= 5000 or not 1 <= top_k <= 10:
            raise HTTPException(422, "Invalid task_description or top_k.")
        session = self._session(db, project, source_agent, session_id, task_description)
        origin = "demo" if demo_mode(project) else "hindsight"
        if origin == "demo":
            query_tokens = relevance_tokens(task_description)
            candidates = db.scalars(
                select(DemoMemory).where(DemoMemory.project_id == project.id)
            ).all()
            ranked = sorted(
                (
                    (len(query_tokens & relevance_tokens(item.content)), item)
                    for item in candidates
                ),
                key=lambda pair: pair[0],
                reverse=True,
            )
            memories = [memory_dto(item) for score, item in ranked if score > 0][:top_k]
            for item in memories:
                item["why_relevant"] = "Shared task terms in local demo memory"
        else:
            memories = await self.hindsight.recall(
                project.hindsight_bank_id, project.id, task_description, top_k
            )
            # The bank and strict project tag are the isolation boundary.
            memories = [
                item
                for item in memories
                if not item.get("tags") or f"project:{project.id}" in item["tags"]
            ]

        if session_id is None:
            self.audit.activity(
                db,
                project,
                session,
                "session_started",
                f"{source_agent} session started",
                origin,
            )
        self.audit.activity(
            db,
            project,
            session,
            "task",
            task_description,
            origin,
        )
        self.audit.activity(
            db,
            project,
            session,
            "tool_call",
            task_description,
            origin,
            tool_name=tool_name,
            evidence=memories,
        )
        event = self.audit.memory_event(
            db,
            project,
            session,
            "recalled",
            task_description,
            {"memory_ids": [item["id"] for item in memories], "origin": origin},
        )
        self.audit.activity(
            db,
            project,
            session,
            "recall_evidence",
            f"Recalled {len(memories)} relevant project memories",
            origin,
            evidence=memories,
        )
        db.commit()
        db.refresh(event)
        return {
            "memories": memories,
            "event_id": event.id,
            "session_id": session.id,
            "used_bank_id": project.hindsight_bank_id,
            "origin": origin,
            "mode_label": "Demo mode - local sample memory"
            if origin == "demo"
            else "Hindsight connected",
        }

    async def list_memories(
        self,
        db: Session,
        project_id: str,
        memory_type: str | None = None,
        tag: str | None = None,
    ) -> dict:
        project = project_or_404(db, project_id)
        if memory_type and memory_type not in MEMORY_TYPES:
            raise HTTPException(422, "Unsupported memory_type.")
        if tag and (len(tag) > 60 or tag.startswith("project:")):
            raise HTTPException(422, "Invalid tag.")
        if demo_mode(project):
            rows = db.scalars(
                select(DemoMemory)
                .where(DemoMemory.project_id == project.id)
                .order_by(DemoMemory.created_at.desc())
                .limit(100)
            ).all()
            items = [memory_dto(row) for row in rows]
            if memory_type:
                items = [item for item in items if item["type"] == memory_type]
            if tag:
                items = [item for item in items if tag in item["tags"]]
        else:
            items = await self.hindsight.list_memories(
                project.hindsight_bank_id, project.id, memory_type, tag
            )
        origin = "demo" if demo_mode(project) else "hindsight"
        return {
            "memories": items,
            "count": len(items),
            "origin": origin,
            "mode_label": "Demo mode - local sample memory"
            if origin == "demo"
            else "Hindsight connected",
            "used_bank_id": project.hindsight_bank_id,
        }
