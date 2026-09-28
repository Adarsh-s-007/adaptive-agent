from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from mcp import Client
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.database import get_db
from app.models.entities import (
    AgentActivity,
    AgentSession,
    DemoScenario,
    MemoryEvent,
    Project,
)
from app.schemas.requests import (
    AgentAnswerRequest,
    MemoryCreate,
    ProjectCreate,
    RecallRequest,
)
from app.services.audit_event_service import AuditEventService
from app.services.groq_service import GroqService
from app.services.hindsight_service import HindsightService
from app.services.mcp_server import mcp
from app.services.project_memory_service import ProjectMemoryService, demo_mode

DBSession = Annotated[Session, Depends(get_db)]

router = APIRouter()
hindsight = HindsightService()
groq = GroqService()
memory_service = ProjectMemoryService(hindsight)


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
        "memory_mode": "demo" if demo_mode(project) else "hindsight",
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
        hindsight_bank_id=(
            hindsight.bank_slug(name, project_id)
            if get_settings().hindsight_api_key
            else "demo-" + hindsight.bank_slug(name, project_id)
        ),
    )
    if not demo_mode(project):
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


@router.get("/projects/{project_id}/memories")
async def list_memories(
    project_id: str,
    db: DBSession,
    memory_type: str | None = None,
    tag: str | None = None,
):
    return await memory_service.list_memories(db, project_id, memory_type, tag)


@router.post("/projects/{project_id}/memories", status_code=201)
async def retain(project_id: str, body: MemoryCreate, db: DBSession):
    result = await memory_service.retain(
        db,
        project_id,
        body.content,
        body.memory_type,
        body.tags,
        body.source_agent,
        tool_name="dashboard.retain_memory",
    )
    event = db.get(MemoryEvent, result["event_id"])
    return {
        "event": event_dto(event, body.source_agent),
        "memory": result["memory"],
        "origin": result["origin"],
        "mode_label": result["mode_label"],
    }


@router.post("/projects/{project_id}/recall")
async def recall(project_id: str, body: RecallRequest, db: DBSession):
    result = await memory_service.recall(
        db,
        project_id,
        body.task,
        body.limit,
        source_agent="Dashboard recall",
        tool_name="dashboard.recall",
    )
    event = db.get(MemoryEvent, result["event_id"])
    return {
        "memories": result["memories"],
        "event": event_dto(event, "Dashboard recall"),
        "used_bank_id": result["used_bank_id"],
        "origin": result["origin"],
    }


@router.get("/projects/{project_id}/activity")
def activity(project_id: str, db: DBSession):
    project_or_404(db, project_id)
    rows = db.scalars(
        select(AgentActivity)
        .where(AgentActivity.project_id == project_id)
        .order_by(AgentActivity.created_at.desc(), AgentActivity.id.desc())
        .limit(100)
    ).all()
    session_ids = {row.session_id for row in rows if row.session_id}
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
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "tool_name": row.tool_name,
            "summary": row.summary,
            "evidence": json.loads(row.evidence_json or "[]"),
            "origin": row.origin,
            "session_id": row.session_id,
            "agent_name": names.get(row.session_id),
            "created_at": row.created_at,
        }
        for row in rows
    ]


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


@router.post("/projects/{project_id}/run-mcp-demo")
async def run_mcp_demo(project_id: str, db: DBSession):
    """Invoke the registered MCP tool, then log a labelled local sample result."""
    project = project_or_404(db, project_id)
    task = "Implement login and refresh-token flow for this project."
    async with Client(mcp) as client:
        result = await client.call_tool(
            "recall_project_memory",
            {"project_id": project.id, "task_description": task, "top_k": 5},
        )
    if result.is_error:
        raise HTTPException(502, "The MCP recall tool did not complete.")
    payload = result.structured_content
    if not isinstance(payload, dict):
        try:
            payload = json.loads(result.content[0].text)
        except (IndexError, AttributeError, ValueError) as exc:
            raise HTTPException(
                502, "The MCP tool returned no structured result."
            ) from exc
    memories = payload.get("memories", [])
    jwt_seen = any(
        "http-only" in item.get("text", "").lower()
        or "httponly" in item.get("text", "").lower()
        for item in memories
    )
    if jwt_seen:
        sample = (
            "Local sample result - not an external coding agent: "
            "Use short-lived access tokens and put refresh tokens in HttpOnly, "
            "Secure cookies. Rotate refresh tokens on use. Do not use LocalStorage."
        )
    else:
        sample = (
            "Local sample result - not an external coding agent: "
            "No JWT storage rule was recalled. Confirm the project's security "
            "decision before choosing refresh-token storage."
        )
    session = db.get(AgentSession, payload["session_id"])
    AuditEventService.activity(
        db,
        project,
        session,
        "agent_result",
        sample,
        payload["origin"],
        evidence=memories,
    )
    db.commit()
    return {
        "tool_call": "projectpulse.recall_project_memory",
        "task": task,
        "memories": memories,
        "sample_result": sample,
        "session_id": payload["session_id"],
        "origin": payload["origin"],
        "mode_label": payload["mode_label"],
    }


# Stable IDs make repeated demo seeds safe in both Hindsight and local demo mode.
SEED = [
    (
        "jwt-security-v2",
        "security_rule",
        "JWT refresh tokens must use HTTP-only, Secure cookies. LocalStorage is forbidden.",
        ["authentication", "security"],
    ),
    (
        "task-api-v2",
        "api_contract",
        "POST /api/tasks returns the created task with HTTP 201.",
        ["tasks", "api"],
    ),
    (
        "order-delete-v2",
        "architecture_decision",
        "Orders use soft deletes to preserve audit history.",
        ["orders", "data"],
    ),
    (
        "payment-pool-v2",
        "incident_fix",
        "Payment worker connection-pool exhaustion was fixed by limiting pool size and queueing retries.",
        ["payments", "incident"],
    ),
    (
        "react-query-v2",
        "coding_convention",
        "Use React Query for server state; do not duplicate API state in global client stores.",
        ["frontend", "react"],
    ),
    (
        "payment-rollback-v2",
        "incident_fix",
        "Rollback alone did not solve the payment-timeout incident.",
        ["payments", "failed-approach"],
    ),
    (
        "signed-images-v2",
        "architecture_decision",
        "Product images are uploaded through a signed URL flow.",
        ["images", "uploads"],
    ),
    (
        "cart-local-v2",
        "architecture_decision",
        "Cart state remains local until checkout succeeds.",
        ["cart", "checkout"],
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

    seeded = 0
    for slug, kind, content, tags in SEED:
        document_id = f"seed-{slug}"
        if document_id in existing:
            continue
        await memory_service.retain(
            db,
            project.id,
            content,
            kind,
            tags,
            source_agent="Agent A - previous session",
            document_id=document_id,
            tool_name="demo.seed",
        )
        seeded += 1

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
                task="Implement login and refresh-token flow for this project.",
                expected_memory_ids="[]",
            )
        )
    db.commit()
    return {
        "seeded": seeded,
        "project": project_dto(project),
        "mode_label": (
            "Demo mode - local sample memory"
            if demo_mode(project)
            else "Hindsight connected"
        ),
    }
