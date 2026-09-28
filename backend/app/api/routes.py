from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.entities import AgentSession, DemoScenario, MemoryEvent, Project
from app.schemas.requests import (
    AgentAnswerRequest,
    MemoryCreate,
    ProjectCreate,
    RecallRequest,
)
from app.services.groq_service import GroqService
from app.services.hindsight_service import HindsightService

DBSession = Annotated[Session, Depends(get_db)]

router = APIRouter()
hindsight = HindsightService()
groq = GroqService()


def project_or_404(db: Session, project_id: str) -> Project:
    try:
        uuid.UUID(project_id)
    except ValueError as exc:
        raise HTTPException(422, "project_id must be a UUID.") from exc
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found.")
    return project


def project_dto(project: Project) -> dict:
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "hindsight_bank_id": project.hindsight_bank_id,
        "created_at": project.created_at,
    }


def event_dto(event: MemoryEvent, agent_name: str | None = None) -> dict:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "source_text": event.source_text,
        "hindsight_memory_reference": event.hindsight_memory_reference,
        "session_id": event.session_id,
        "agent_name": agent_name,
        "created_at": event.created_at,
    }


def reference_ids(memories: list[dict]) -> str:
    return json.dumps([memory["id"] for memory in memories])


def retained_content(project: Project, kind: str, agent: str, text: str) -> str:
    return (
        f"Memory type: {kind}\nSource agent: {agent}\nProject: {project.name}\n"
        f"Decision / learning: {text}"
    )


@router.post("/projects", status_code=201)
async def create_project(body: ProjectCreate, db: DBSession):
    name = body.name.strip()
    if db.scalar(select(Project).where(Project.name == name)):
        raise HTTPException(409, "A project with that name already exists.")
    project_id = str(uuid.uuid4())
    project = Project(
        id=project_id,
        name=name,
        description=body.description.strip(),
        hindsight_bank_id=hindsight.bank_slug(name, project_id),
    )
    await hindsight.create_bank(
        project.hindsight_bank_id, project.name, project.description
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project_dto(project)


@router.get("/projects")
def projects(db: DBSession):
    return [
        project_dto(project)
        for project in db.scalars(
            select(Project).order_by(Project.created_at.desc())
        ).all()
    ]


@router.get("/projects/{project_id}")
def project(project_id: str, db: DBSession):
    return project_dto(project_or_404(db, project_id))


@router.get("/projects/{project_id}/timeline")
def timeline(project_id: str, db: DBSession):
    project_or_404(db, project_id)
    events = db.scalars(
        select(MemoryEvent)
        .where(MemoryEvent.project_id == project_id)
        .order_by(MemoryEvent.created_at.desc(), MemoryEvent.id.desc())
        .limit(100)
    ).all()
    session_ids = {event.session_id for event in events if event.session_id}
    names = (
        {
            session.id: session.agent_name
            for session in db.scalars(
                select(AgentSession).where(AgentSession.id.in_(session_ids))
            ).all()
        }
        if session_ids
        else {}
    )
    return [event_dto(event, names.get(event.session_id)) for event in events]


@router.get("/projects/{project_id}/stats")
def stats(project_id: str, db: DBSession):
    project_or_404(db, project_id)
    rows = db.execute(
        select(MemoryEvent.event_type, func.count())
        .where(MemoryEvent.project_id == project_id)
        .group_by(MemoryEvent.event_type)
    ).all()
    result = {"retained": 0, "recalled": 0, "decisions": 0, "bug_fixes": 0}
    for event_type, count in rows:
        if event_type in result:
            result[event_type] = count
    result["decisions"] = (
        db.scalar(
            select(func.count())
            .select_from(MemoryEvent)
            .where(
                MemoryEvent.project_id == project_id,
                MemoryEvent.event_type == "retained",
                MemoryEvent.source_text.like("Memory type: architecture decision%"),
            )
        )
        or 0
    )
    result["bug_fixes"] = (
        db.scalar(
            select(func.count())
            .select_from(MemoryEvent)
            .where(
                MemoryEvent.project_id == project_id,
                MemoryEvent.event_type == "retained",
                MemoryEvent.source_text.like("Memory type: bug fix%"),
            )
        )
        or 0
    )
    return result


@router.post("/projects/{project_id}/memories", status_code=201)
async def retain(project_id: str, body: MemoryCreate, db: DBSession):
    project = project_or_404(db, project_id)
    document_id = f"memory-{uuid.uuid4()}"
    content = retained_content(
        project, body.memory_type, body.source_agent.strip(), body.content.strip()
    )
    response = await hindsight.retain(
        project.hindsight_bank_id,
        content=content,
        document_id=document_id,
        metadata={
            "project_id": project.id,
            "memory_type": body.memory_type,
            "source_agent": body.source_agent.strip(),
        },
        tags=[f"project:{project.id}", f"type:{body.memory_type.replace(' ', '-')}"],
    )
    if response.get("success") is False:
        raise HTTPException(502, "Hindsight did not confirm the Retain operation.")
    session = AgentSession(
        project_id=project.id,
        agent_name=body.source_agent.strip(),
        task="Retain project learning",
    )
    db.add(session)
    db.flush()
    event = MemoryEvent(
        project_id=project.id,
        session_id=session.id,
        event_type="retained",
        source_text=content,
        hindsight_memory_reference=json.dumps({"document_id": document_id}),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {"event": event_dto(event, session.agent_name), "hindsight": response}


@router.post("/projects/{project_id}/recall")
async def recall(project_id: str, body: RecallRequest, db: DBSession):
    project = project_or_404(db, project_id)
    candidates = await hindsight.recall(
        project.hindsight_bank_id, project.id, body.task.strip(), body.limit
    )
    memories = await groq.select_relevant(body.task.strip(), candidates)
    event = MemoryEvent(
        project_id=project.id,
        event_type="recalled",
        source_text=body.task.strip(),
        hindsight_memory_reference=reference_ids(memories),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {
        "memories": memories,
        "event": event_dto(event),
        "used_bank_id": project.hindsight_bank_id,
    }


@router.post("/projects/{project_id}/agent-answer")
async def answer(project_id: str, body: AgentAnswerRequest, db: DBSession):
    project = project_or_404(db, project_id)
    task = body.task.strip()
    candidates = await hindsight.recall(
        project.hindsight_bank_id, project.id, task, body.limit
    )
    memories = await groq.select_relevant(task, candidates)
    session = AgentSession(
        project_id=project.id, agent_name=body.agent_name.strip(), task=task
    )
    db.add(session)
    db.flush()
    event = MemoryEvent(
        project_id=project.id,
        session_id=session.id,
        event_type="recalled",
        source_text=task,
        hindsight_memory_reference=reference_ids(memories),
    )
    db.add(event)
    db.commit()
    db.refresh(session)
    db.refresh(event)

    generic_prompt = (
        f"Project: {project.name}\nCurrent task: {task}\n"
        "Give a short general implementation outline. List choices where the "
        "project's prior decision would matter."
    )
    generic_answer = await groq.answer(generic_prompt)
    if memories:
        evidence = "\n".join(
            f"- [{memory['id']}] {memory['text']}"
            + (
                f" Source: {memory['source_text'][:500]}"
                if memory.get("source_text")
                else ""
            )
            for memory in memories
        )
        aware_prompt = (
            f"You are an engineering assistant for {project.name}.\n\n"
            f"Current task:\n{task}\n\n"
            f"Relevant project memories:\n{evidence}\n\n"
            "Follow these retained project decisions where applicable. "
            "If memories conflict or are insufficient, state that clearly instead "
            "of inventing a rule. Name concrete decisions from the evidence."
        )
        memory_aware_answer = await groq.answer(aware_prompt, memory_aware=True)
    else:
        memory_aware_answer = generic_answer

    return {
        "generic_answer": generic_answer,
        "memory_aware_answer": memory_aware_answer,
        "memories": memories,
        "session": {
            "id": session.id,
            "agent_name": session.agent_name,
            "created_at": session.created_at,
        },
        "event": event_dto(event, session.agent_name),
        "used_bank_id": project.hindsight_bank_id,
    }


# A deterministic document ID makes re-seeding safe after a partial provider failure.
SEED = [
    (
        "jwt-cookie-rule",
        "architecture decision",
        "JWT refresh tokens must be stored in HTTP-only cookies. Never use localStorage because it increases XSS exposure.",
    ),
    (
        "payment-pool-fix",
        "bug fix",
        "Payment timeouts were caused by database connection-pool exhaustion; increasing the pool size worked.",
    ),
    (
        "task-api-contract",
        "coding convention",
        "POST /api/tasks returns taskId and uses one fixed validation-error format.",
    ),
    (
        "react-query-state",
        "coding convention",
        "React Query owns server state; do not duplicate it in a global store.",
    ),
    (
        "orders-soft-delete",
        "architecture decision",
        "Orders use soft delete; never permanently delete completed orders.",
    ),
    (
        "rollback-failed",
        "failed approach",
        "Rollback alone did not solve the payment-timeout incident.",
    ),
    (
        "signed-product-images",
        "feature progress",
        "Product images are uploaded through a signed URL flow.",
    ),
    (
        "cart-local-state",
        "architecture decision",
        "Cart state remains local until checkout succeeds.",
    ),
]


@router.post("/projects/{project_id}/seed-demo-data")
async def seed(project_id: str, db: DBSession):
    project = project_or_404(db, project_id)
    if project.name != "E-commerce Platform":
        raise HTTPException(400, "Demo data is only available for E-commerce Platform.")

    existing = set()
    for event in db.scalars(
        select(MemoryEvent).where(
            MemoryEvent.project_id == project.id,
            MemoryEvent.event_type == "retained",
        )
    ).all():
        try:
            reference = json.loads(event.hindsight_memory_reference or "{}")
            if isinstance(reference, dict):
                existing.add(reference.get("document_id"))
        except json.JSONDecodeError:
            continue

    pending = [
        (f"seed-{slug}", kind, text)
        for slug, kind, text in SEED
        if f"seed-{slug}" not in existing
    ]
    if pending:
        agent = "Agent A - previous session"
        now = datetime.now(timezone.utc).isoformat()
        items = [
            {
                "content": retained_content(project, kind, agent, text),
                "document_id": document_id,
                "metadata": {
                    "project_id": project.id,
                    "memory_type": kind,
                    "source_agent": agent,
                    "seed": "true",
                },
                "tags": [f"project:{project.id}", f"type:{kind.replace(' ', '-')}"],
                "timestamp": now,
            }
            for document_id, kind, text in pending
        ]
        response = await hindsight.retain_batch(project.hindsight_bank_id, items)
        if response.get("success") is False:
            raise HTTPException(
                502, "Hindsight did not confirm the demo Retain operation."
            )
        session = AgentSession(
            project_id=project.id,
            agent_name=agent,
            task="Retain E-commerce demo decisions",
        )
        db.add(session)
        db.flush()
        for document_id, kind, text in pending:
            db.add(
                MemoryEvent(
                    project_id=project.id,
                    session_id=session.id,
                    event_type="retained",
                    source_text=retained_content(project, kind, agent, text),
                    hindsight_memory_reference=json.dumps({"document_id": document_id}),
                )
            )

    scenario = db.scalar(
        select(DemoScenario).where(
            DemoScenario.project_id == project.id,
            DemoScenario.title == "Fresh Agent B: authentication",
        )
    )
    if not scenario:
        db.add(
            DemoScenario(
                project_id=project.id,
                title="Fresh Agent B: authentication",
                task="Build the login screen and authentication flow.",
                expected_memory_ids="[]",
            )
        )
    db.commit()
    return {"seeded": len(pending), "project": project_dto(project)}
