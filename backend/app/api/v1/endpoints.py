"""FastAPI route handlers for /api/v1 endpoints per Blueprint C-8."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, AppErrorCode
from app.core.security import verify_bearer_token
from app.db.database import get_db
from app.db.governed_models import (
    ComparisonRun,
    MemoryCandidate,
    MemoryRecord,
    SessionTurn,
)
from app.gateways.hindsight_gateway import HindsightGateway
from app.gateways.llm_gateway import LLMGateway
from app.models.entities import AgentSession
from app.schemas.common import (
    BriefResult,
    CheckResult,
    CompareResult,
    MemoryRecordOut,
)
from app.services.brief_service import BriefService
from app.services.check_service import CheckService
from app.services.compare_service import CompareService
from app.services.extraction_validator import ExtractionValidator
from app.services.generation_service import GenerationService
from app.services.governed_memory_service import GovernedMemoryService
from app.services.project_memory_service import project_or_404
from app.services.review_service import ReviewService
from app.services.signals import TranscriptPreparer
from app.services.transcript_parser import TranscriptParser

router = APIRouter(dependencies=[Depends(verify_bearer_token)])
DBSession = Annotated[Session, Depends(get_db)]

# Services
hindsight_gw = HindsightGateway()
llm_gw = LLMGateway()
mem_service = GovernedMemoryService(hindsight_gw)
brief_service = BriefService(hindsight_gw, llm_gw, mem_service)
check_service = CheckService(hindsight_gw, llm_gw, mem_service)
gen_service = GenerationService(llm_gw, brief_service)
compare_service = CompareService(gen_service, check_service)
review_service = ReviewService(mem_service)


# --- Request Models ---

class BriefRequest(BaseModel):
    task: str = Field(..., min_length=3, max_length=5000)
    file_paths: list[str] | None = None


class CheckRequest(BaseModel):
    content: str = Field(..., min_length=5)
    run_id: str | None = None


class CompareRequest(BaseModel):
    task: str = Field(..., min_length=3)


class GovernedMemoryCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    statement: str = Field(..., min_length=15, max_length=12000)
    memory_type: str
    rationale: str | None = None
    area: str | None = None
    importance: int = Field(default=3, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    evidence_quote: str | None = None
    check_patterns: list[str] = Field(default_factory=list)


class SupersedeRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    statement: str = Field(..., min_length=15, max_length=12000)
    rationale: str | None = None
    area: str | None = None
    importance: int = Field(default=3, ge=1, le=5)
    evidence_quote: str | None = None


class TranscriptImportRequest(BaseModel):
    title: str = "Imported Session"
    transcript: str = Field(..., min_length=10, max_length=200000)
    format_hint: str = "markdown"  # markdown, jsonl, plain
    developer: str = "Developer"
    agent_label: str = "Coding Agent"


class CandidateReviewRequest(BaseModel):
    resolution: str = "new"  # new, supersede, keep_both, add_evidence
    target_record_id: str | None = None
    edited_title: str | None = None
    edited_statement: str | None = None
    reviewer: str = "Reviewer"


# --- Brief Endpoint ---

@router.post("/projects/{pid}/brief", response_model=BriefResult)
async def get_brief(pid: str, body: BriefRequest, db: DBSession):
    """Obtain task Brief: applied rules, reasons, and injected tokens (BR-2)."""
    return await brief_service.build_brief(db, pid, body.task, body.file_paths)


# --- Check Endpoint ---

@router.post("/projects/{pid}/check", response_model=CheckResult)
async def check_compliance(pid: str, body: CheckRequest, db: DBSession):
    """Validate code or diff against governed project decisions (CK-3)."""
    return await check_service.check(db, pid, body.content, body.run_id)


# --- Compare Endpoints ---

@router.post("/projects/{pid}/compare", response_model=CompareResult)
async def run_comparison(pid: str, body: CompareRequest, db: DBSession):
    """Run baseline vs memory-aware trial and compute violation delta (CP-2)."""
    return await compare_service.compare(db, pid, body.task)


@router.get("/projects/{pid}/compare/{cid}", response_model=CompareResult)
def get_comparison(pid: str, cid: str, db: DBSession):
    """Retrieve comparison run progress or results."""
    comp = db.get(ComparisonRun, cid)
    if not comp or comp.project_id != pid:
        raise AppError(code=AppErrorCode.NOT_FOUND, message="Comparison run not found.", status_code=404)
    return CompareResult(
        id=comp.id,
        status=comp.status,
        stage=comp.stage,
        violations_baseline=comp.violations_baseline,
        violations_memory=comp.violations_memory,
        violation_delta=comp.violation_delta,
        applied_count=comp.applied_count,
        injected_tokens=comp.injected_tokens,
        fairness=json.loads(comp.fairness_json or "{}"),
        created_at=comp.created_at.isoformat(),
    )


# --- Governed Records Endpoints ---

@router.get("/projects/{pid}/memories", response_model=list[MemoryRecordOut])
def list_governed_records(
    pid: str,
    db: DBSession,
    status: str = "active",
    area: str | None = None,
    q: str | None = None,
):
    """List governed records with filtering."""
    query = select(MemoryRecord).where(MemoryRecord.project_id == pid)
    if status:
        query = query.where(MemoryRecord.status == status)
    if area:
        query = query.where(MemoryRecord.area == area)
    
    records = db.scalars(query.order_by(MemoryRecord.importance.desc(), MemoryRecord.decided_at.desc())).all()
    
    if q:
        kw = q.lower()
        records = [r for r in records if kw in r.title.lower() or kw in r.statement.lower()]

    return [
        MemoryRecordOut(
            id=r.id,
            pill=r.pill,
            project_id=r.project_id,
            type=r.type,
            title=r.title,
            statement=r.statement,
            rationale=r.rationale,
            area=r.area,
            importance=r.importance,
            status=r.status,
            confidence_band=r.confidence_band,
            decided_at=r.decided_at.isoformat(),
            tentative=r.tentative,
            tags=json.loads(r.tags_json or "[]"),
            metadata=json.loads(r.metadata_json or "{}"),
            hindsight_document_id=r.hindsight_document_id,
            retain_state=r.retain_state,
            evidence_count=len(r.evidence),
            review_due=False,
            supersedes=r.supersedes_id,
            superseded_by=r.superseded_by_id,
            check_patterns=json.loads(r.check_patterns_json or "[]"),
            created_at=r.created_at.isoformat(),
            updated_at=r.updated_at.isoformat() if r.updated_at else None,
        )
        for r in records
    ]


@router.post("/projects/{pid}/memories", response_model=MemoryRecordOut, status_code=201)
async def create_governed_record(pid: str, body: GovernedMemoryCreate, db: DBSession):
    """Create a new governed record through the outbox pattern."""
    record = await mem_service.create_record(
        db=db,
        project_id=pid,
        title=body.title,
        statement=body.statement,
        memory_type=body.memory_type,
        rationale=body.rationale,
        area=body.area,
        importance=body.importance,
        evidence_quote=body.evidence_quote,
        tags=body.tags,
        check_patterns=body.check_patterns,
    )
    return MemoryRecordOut(
        id=record.id,
        pill=record.pill,
        project_id=record.project_id,
        type=record.type,
        title=record.title,
        statement=record.statement,
        rationale=record.rationale,
        area=record.area,
        importance=record.importance,
        status=record.status,
        confidence_band=record.confidence_band,
        decided_at=record.decided_at.isoformat(),
        tags=json.loads(record.tags_json or "[]"),
        metadata=json.loads(record.metadata_json or "{}"),
        hindsight_document_id=record.hindsight_document_id,
        retain_state=record.retain_state,
        evidence_count=1 if body.evidence_quote else 0,
        review_due=False,
        created_at=record.created_at.isoformat(),
    )


@router.post("/projects/{pid}/memories/{id}/supersede", response_model=MemoryRecordOut)
async def supersede_governed_record(pid: str, id: str, body: SupersedeRequest, db: DBSession):
    """Execute 5-step supersession protocol on an active record (RC-2)."""
    record = await mem_service.supersede(
        db=db,
        old_record_id=id,
        title=body.title,
        statement=body.statement,
        rationale=body.rationale,
        area=body.area,
        importance=body.importance,
        evidence_quote=body.evidence_quote,
    )
    return MemoryRecordOut(
        id=record.id,
        pill=record.pill,
        project_id=record.project_id,
        type=record.type,
        title=record.title,
        statement=record.statement,
        rationale=record.rationale,
        area=record.area,
        importance=record.importance,
        status=record.status,
        confidence_band=record.confidence_band,
        decided_at=record.decided_at.isoformat(),
        tags=json.loads(record.tags_json or "[]"),
        metadata=json.loads(record.metadata_json or "{}"),
        hindsight_document_id=record.hindsight_document_id,
        retain_state=record.retain_state,
        supersedes=record.supersedes_id,
        created_at=record.created_at.isoformat(),
    )


# --- Session Import & Candidate Review Endpoints ---

@router.post("/projects/{pid}/sessions/import", status_code=201)
async def import_session_transcript(pid: str, body: TranscriptImportRequest, db: DBSession):
    """Import transcript, parse turns, extract candidates, and populate Inbox (EX-1, EX-2)."""
    project = project_or_404(db, pid)

    # 1. Parse and scrub turns
    parsed_turns = TranscriptParser.parse(body.transcript, body.format_hint)
    prepared_turns = TranscriptPreparer.prepare_turns(parsed_turns)

    # 2. Create AgentSession
    session = AgentSession(
        project_id=pid,
        agent_name=body.agent_label,
        task=body.title,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    # 3. Store SessionTurns
    turn_texts = []
    for t in prepared_turns:
        db.add(SessionTurn(session_id=session.id, turn_index=t.turn_index, role=t.role, content=t.content))
        turn_texts.append(t.content)
    db.commit()

    # 4. Extract candidates using signal extraction & validator
    candidates_created = 0
    for t in prepared_turns:
        if t.role == "tool":
            continue
        hints = TranscriptPreparer.find_signal_hints(t.content)
        if hints:
            # Extract candidate candidate sentence
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
                    project_id=pid,
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
                candidates_created += 1

    db.commit()
    return {
        "session_id": session.id,
        "turns_imported": len(prepared_turns),
        "candidates_extracted": candidates_created,
        "message": "Session imported. Candidates awaiting review in Inbox.",
    }


@router.get("/projects/{pid}/candidates")
def list_candidates(pid: str, db: DBSession, status: str = "pending"):
    """List candidates awaiting review in Inbox (GV-1)."""
    candidates = review_service.list_candidates(db, pid, status)
    return [
        {
            "id": c.id,
            "session_id": c.session_id,
            "type": c.type,
            "title": c.title,
            "statement": c.statement,
            "evidence_quote": c.evidence_quote,
            "status": c.status,
            "confidence": c.confidence,
            "flagged": c.flagged,
            "filter_reason": c.filter_reason,
            "created_at": c.created_at.isoformat(),
        }
        for c in candidates
    ]


@router.post("/projects/{pid}/candidates/{cid}/review")
async def review_candidate(pid: str, cid: str, body: CandidateReviewRequest, db: DBSession):
    """Approve or reject candidate with specified resolution (GV-1)."""
    if body.resolution == "reject":
        res = review_service.reject_candidate(db, cid, "Rejected during review.")
        return {"status": "rejected", "candidate_id": res.id}

    res = await review_service.approve_candidate(
        db=db,
        candidate_id=cid,
        resolution=body.resolution,
        target_record_id=body.target_record_id,
        edited_title=body.edited_title,
        edited_statement=body.edited_statement,
        reviewer=body.reviewer,
    )
    return {"status": "approved", "resolution": body.resolution, "id": getattr(res, "id", "")}
