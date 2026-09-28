"""ProjectPulse MCP tools (recall/retain/list + governed Brief, Check, Submit, Ask, Rulebook)."""

from __future__ import annotations

from typing import Literal

from mcp.server import MCPServer

from app.db.database import SessionLocal
from app.services.project_memory_service import ProjectMemoryService

mcp = MCPServer("projectpulse-mcp")
service = ProjectMemoryService()

MemoryType = Literal[
    "architecture_decision",
    "security_rule",
    "api_contract",
    "incident_fix",
    "coding_convention",
]


@mcp.tool()
async def recall_project_memory(
    project_id: str, task_description: str, top_k: int = 5
) -> dict:
    """Recall only task-relevant memories from this project's isolated bank."""
    with SessionLocal() as db:
        return await service.recall(
            db,
            project_id,
            task_description,
            top_k,
            source_agent="Fresh Agent B",
        )


@mcp.tool()
async def retain_project_memory(
    project_id: str,
    content: str,
    memory_type: MemoryType,
    tags: list[str],
    source_agent: str = "Coding agent",
    session_id: str | None = None,
) -> dict:
    """Retain a durable engineering fact. Never send secrets or personal data."""
    with SessionLocal() as db:
        return await service.retain(
            db, project_id, content, memory_type, tags, source_agent, session_id
        )


@mcp.tool()
async def list_project_memories(
    project_id: str, memory_type: MemoryType | None = None, tag: str | None = None
) -> dict:
    """Inspect memories in one project's bank, optionally filtered."""
    with SessionLocal() as db:
        return await service.list_memories(db, project_id, memory_type, tag)


async def _governed(call):
    """Run a governed-memory service call in a fresh DB session with the shared services."""
    from app.services.container import services

    with SessionLocal() as db:
        return await call(services(), db)


@mcp.tool()
async def projectpulse_brief(project_id: str, task: str, file_paths: list[str] | None = None) -> dict:
    """Call BEFORE implementing a task: returns the reviewed project decisions that apply
    (max 5, each with a reason), what was filtered out and why, and a ready-to-follow
    <project_memory> block. Follow the applied records unless the task explicitly changes one."""

    async def call(svc, db):
        result = await svc.brief.build_brief(db, project_id, task, file_paths or [])
        return result.model_dump()

    return await _governed(call)


@mcp.tool()
async def projectpulse_check(project_id: str, content: str) -> dict:
    """Call AFTER writing code or a plan: checks the content against the project's reviewed
    decisions and returns violations (with the offending excerpt, the violated record and a
    suggested fix), warnings and conflicts. Fix every violation before finishing."""

    async def call(svc, db):
        result = await svc.check.check(db, project_id, content)
        return result.model_dump()

    return await _governed(call)


@mcp.tool()
async def projectpulse_submit_session(
    project_id: str,
    transcript: str,
    title: str = "Agent session",
    format_hint: str = "markdown",
    developer: str = "Developer",
    agent_label: str = "MCP agent",
) -> dict:
    """Submit a finished session transcript. ProjectPulse extracts typed memory candidates with
    verbatim evidence; a human reviews them in the Inbox before anything reaches memory."""

    async def call(svc, db):
        session = svc.sessions.import_transcript(
            db,
            project_id,
            title=title,
            text=transcript,
            developer=developer,
            agent_label=agent_label,
            format_hint=format_hint,
            source="mcp",
        )
        extracted = await svc.extraction.extract_session(db, project_id, session.id)
        return {
            "session_id": session.id,
            "turns_imported": session.turn_count,
            "candidates_extracted": len(extracted["candidates"]),
            "stats": extracted["stats"],
            "status": "awaiting_human_review_in_inbox",
        }

    return await _governed(call)


@mcp.tool()
async def projectpulse_ask(project_id: str, question: str) -> dict:
    """Ask the project's memory a "why" question (Hindsight reflect) and get an answer with
    citations to the reviewed records it is based on."""

    async def call(svc, db):
        return await svc.reflect.ask(db, project_id, question)

    return await _governed(call)


@mcp.tool()
async def projectpulse_rulebook(project_id: str, format: str = "claude_md") -> dict:
    """Export the project's active, human-reviewed rules as CLAUDE.md or .cursorrules content."""

    async def call(svc, db):
        return svc.reflect.export(db, project_id, format)

    return await _governed(call)
