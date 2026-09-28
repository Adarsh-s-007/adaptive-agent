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


@mcp.tool()
async def projectpulse_brief(
    project_id: str, task: str, file_paths: list[str] | None = None
) -> dict:
    """Obtain task Brief before implementing code: applied rules, reasons, and provenance (Blueprint §22)."""
    file_paths = file_paths or []
    from app.gateways.hindsight_gateway import HindsightGateway
    from app.gateways.llm_gateway import LLMGateway
    from app.services.brief_service import BriefService
    from app.services.governed_memory_service import GovernedMemoryService

    h_gw = HindsightGateway()
    llm_gw = LLMGateway()
    g_mem = GovernedMemoryService(h_gw)
    b_svc = BriefService(h_gw, llm_gw, g_mem)
    with SessionLocal() as db:
        result = await b_svc.build_brief(db, project_id, task, file_paths)
        return result.model_dump()


@mcp.tool()
async def projectpulse_check(
    project_id: str, content: str
) -> dict:
    """Check code or proposed changes against governed project decisions before finalizing (Blueprint §22)."""
    from app.gateways.hindsight_gateway import HindsightGateway
    from app.gateways.llm_gateway import LLMGateway
    from app.services.check_service import CheckService
    from app.services.governed_memory_service import GovernedMemoryService

    h_gw = HindsightGateway()
    llm_gw = LLMGateway()
    g_mem = GovernedMemoryService(h_gw)
    c_svc = CheckService(h_gw, llm_gw, g_mem)
    with SessionLocal() as db:
        result = await c_svc.check(db, project_id, content)
        return result.model_dump()


@mcp.tool()
async def projectpulse_submit_session(
    project_id: str, transcript: str, title: str = "Agent Session", format_hint: str = "markdown"
) -> dict:
    """Submit transcript from any coding agent to import turns and extract candidates into the human review Inbox (Blueprint §22)."""
    from app.db.governed_models import MemoryCandidate, SessionTurn
    from app.models.entities import AgentSession
    from app.services.extraction_validator import ExtractionValidator
    from app.services.signals import TranscriptPreparer
    from app.services.transcript_parser import TranscriptParser

    with SessionLocal() as db:
        parsed_turns = TranscriptParser.parse(transcript, format_hint)
        prepared_turns = TranscriptPreparer.prepare_turns(parsed_turns)

        session = AgentSession(project_id=project_id, agent_name="MCP Agent", task=title)
        db.add(session)
        db.commit()
        db.refresh(session)

        turn_texts = []
        for t in prepared_turns:
            db.add(SessionTurn(session_id=session.id, turn_index=t.turn_index, role=t.role, content=t.content))
            turn_texts.append(t.content)
        db.commit()

        candidates_count = 0
        for t in prepared_turns:
            if t.role == "tool":
                continue
            hints = TranscriptPreparer.find_signal_hints(t.content)
            if hints:
                sentences = [s.strip() for s in t.content.split(".") if len(s.strip()) >= 20]
                for s in sentences[:2]:
                    val = ExtractionValidator.validate(
                        statement=s,
                        memory_type="architecture_decision",
                        evidence_quote=s,
                        transcript_texts=turn_texts,
                        stated_by=t.role,
                    )
                    cand = MemoryCandidate(
                        session_id=session.id,
                        project_id=project_id,
                        type="architecture_decision",
                        title=s[:60] + "...",
                        statement=s,
                        evidence_quote=s,
                        status=val.status,
                        filter_reason=val.reason,
                        confidence=val.adjusted_confidence,
                        flagged=val.flagged,
                    )
                    db.add(cand)
                    candidates_count += 1
        db.commit()
        return {
            "session_id": session.id,
            "turns_imported": len(prepared_turns),
            "candidates_extracted": candidates_count,
            "status": "awaiting_human_review_in_inbox",
        }


@mcp.tool()
async def projectpulse_ask(
    project_id: str, question: str
) -> dict:
    """Ask technical questions about the project's architecture, decisions, and patterns (Blueprint §4.3)."""
    from app.gateways.hindsight_gateway import HindsightGateway
    from app.gateways.project_context import BankResolver

    h_gw = HindsightGateway()
    with SessionLocal() as db:
        ctx = BankResolver.resolve(db, project_id)
        result = await h_gw.reflect(ctx, question)
        return result
