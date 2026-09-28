"""The three ProjectPulse MCP tools, shared by stdio and the local demo."""

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
