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
from app.services.metrics_service import MetricsService
from app.services.project_memory_service import project_or_404
from app.services.project_service import ProjectService
from app.services.review_service import ReviewService
from app.services.seed_service import SeedService
from app.services.signals import TranscriptPreparer
from app.services.timeline_service import TimelineService
from app.services.transcript_parser import TranscriptParser

router = APIRouter(dependencies=[Depends(verify_bearer_token)])
DBSession = Annotated[Session, Depends(get_db)]

# Services
hindsight_gw = HindsightGateway()
llm_gw = LLMGateway()
mem_service = GovernedMemoryService(hindsight_gw)
project_service = ProjectService(hindsight_gw)
brief_service = BriefService(hindsight_gw, llm_gw, mem_service)
check_service = CheckService(hindsight_gw, llm_gw, mem_service)
gen_service = GenerationService(llm_gw, brief_service)
compare_service = CompareService(gen_service, check_service)
review_service = ReviewService(mem_service)
timeline_service = TimelineService()
metrics_service = MetricsService(hindsight_gw)
seed_service = SeedService(mem_service)


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


# --- Project Provisioning, Rulebook & Ask Endpoints (HS-4, RF-1, RF-2) ---

class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)


class OfflineToggleRequest(BaseModel):
    force_offline: bool


@router.post("/projects/{pid}/provision")
async def provision_project(pid: str, db: DBSession):
    """Idempotent retry for project bank provisioning (HS-4)."""
    proj = await project_service.provision_project(db, pid)
    return {
        "project_id": proj.id,
        "bank_id": proj.hindsight_bank_id,
        "bank_status": proj.bank_status,
    }


@router.get("/projects/{pid}/rulebook")
async def get_rulebook(pid: str, db: DBSession):
    """Fetch synthesized Project Rulebook (RF-2)."""
    return await project_service.get_rulebook(db, pid)


@router.post("/projects/{pid}/rulebook/refresh")
async def refresh_rulebook(pid: str, db: DBSession):
    """Force re-synthesis of Project Rulebook (RF-2)."""
    return await project_service.refresh_rulebook(db, pid)


@router.post("/projects/{pid}/ask")
async def ask_project(pid: str, body: AskRequest, db: DBSession):
    """Ask technical question with memory reflection and citation mapping (RF-1)."""
    return await project_service.ask(db, pid, body.question)


@router.get("/admin/hindsight/offline")
def get_hindsight_offline_status():
    """Get status of HINDSIGHT_FORCE_OFFLINE toggle (HS-6)."""
    return {"force_offline": hindsight_gw.is_forced_offline}


@router.post("/admin/hindsight/offline")
def toggle_hindsight_offline(body: OfflineToggleRequest):
    """Set HINDSIGHT_FORCE_OFFLINE toggle for degradation testing (HS-6)."""
    hindsight_gw.set_force_offline(body.force_offline)
    return {"force_offline": hindsight_gw.is_forced_offline}


# --- Governed Records, Timeline, Metrics & Seed Endpoints (P3 / RC-1..7, MT-1) ---

class CreateRecordRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    statement: str = Field(..., min_length=10)
    memory_type: str = Field(default="architecture_decision")
    rationale: str | None = None
    area: str | None = None
    importance: int = Field(default=3, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    check_patterns: list[str] = Field(default_factory=list)
    evidence_quote: str | None = None


class SupersedeRecordRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    statement: str = Field(..., min_length=10)
    rationale: str | None = None
    area: str | None = None
    importance: int = Field(default=3, ge=1, le=5)
    evidence_quote: str | None = None


class RetractRecordRequest(BaseModel):
    reason: str | None = None


class SeedRequest(BaseModel):
    dataset: str = Field(default="apexcart")  # apexcart, ledgerlite


@router.get("/projects/{pid}/records")
def list_governed_records(
    pid: str,
    db: DBSession,
    status: str | None = None,
    memory_type: str | None = None,
    area: str | None = None,
):
    """List governed records for this project with optional status and area filters (RC-1)."""
    project_or_404(db, pid)
    query = select(MemoryRecord).where(MemoryRecord.project_id == pid)
    if status:
        query = query.where(MemoryRecord.status == status)
    if memory_type:
        query = query.where(MemoryRecord.type == memory_type)
    if area:
        query = query.where(MemoryRecord.area == area)
    records = db.scalars(query.order_by(MemoryRecord.importance.desc(), MemoryRecord.decided_at.desc())).all()
    return [
        {
            "id": r.id,
            "pill": r.pill,
            "project_id": r.project_id,
            "type": r.type,
            "title": r.title,
            "statement": r.statement,
            "rationale": r.rationale,
            "area": r.area,
            "importance": r.importance,
            "status": r.status,
            "confidence_band": r.confidence_band,
            "supersedes_id": r.supersedes_id,
            "superseded_by_id": r.superseded_by_id,
            "hindsight_document_id": r.hindsight_document_id,
            "retain_state": r.retain_state,
            "created_at": r.created_at.isoformat(),
        }
        for r in records
    ]


@router.get("/projects/{pid}/records/{rid}")
def get_governed_record(pid: str, rid: str, db: DBSession):
    """Fetch complete governed record details including evidence and lineage (RC-1)."""
    project_or_404(db, pid)
    rec = db.get(MemoryRecord, rid)
    if not rec or rec.project_id != pid:
        raise AppError(code=AppErrorCode.NOT_FOUND, message="Record not found", status_code=404)
    evidence = [
        {"id": ev.id, "quote": ev.quote, "speaker": ev.speaker, "turn_index": ev.turn_index}
        for ev in rec.evidence
    ]
    return {
        "id": rec.id,
        "pill": rec.pill,
        "project_id": rec.project_id,
        "type": rec.type,
        "title": rec.title,
        "statement": rec.statement,
        "rationale": rec.rationale,
        "area": rec.area,
        "importance": rec.importance,
        "status": rec.status,
        "confidence_band": rec.confidence_band,
        "supersedes_id": rec.supersedes_id,
        "superseded_by_id": rec.superseded_by_id,
        "hindsight_document_id": rec.hindsight_document_id,
        "retain_state": rec.retain_state,
        "tags": json.loads(rec.tags_json or "[]"),
        "check_patterns": json.loads(rec.check_patterns_json or "[]"),
        "evidence": evidence,
        "created_at": rec.created_at.isoformat(),
        "updated_at": rec.updated_at.isoformat(),
    }


@router.post("/projects/{pid}/records", status_code=201)
async def create_governed_record(pid: str, body: CreateRecordRequest, db: DBSession):
    """Create and retain a new governed memory record (RC-1)."""
    project_or_404(db, pid)
    rec = await mem_service.create_record(
        db=db,
        project_id=pid,
        title=body.title,
        statement=body.statement,
        memory_type=body.memory_type,
        rationale=body.rationale,
        area=body.area,
        importance=body.importance,
        tags=body.tags,
        check_patterns=body.check_patterns,
        evidence_quote=body.evidence_quote,
    )
    return {
        "id": rec.id,
        "pill": rec.pill,
        "status": rec.status,
        "retain_state": rec.retain_state,
        "title": rec.title,
    }


@router.post("/projects/{pid}/records/{rid}/supersede")
async def supersede_governed_record(pid: str, rid: str, body: SupersedeRecordRequest, db: DBSession):
    """Execute 5-step supersession protocol (RC-2, RC-3)."""
    project_or_404(db, pid)
    new_rec = await mem_service.supersede(
        db=db,
        old_record_id=rid,
        title=body.title,
        statement=body.statement,
        rationale=body.rationale,
        area=body.area,
        importance=body.importance,
        evidence_quote=body.evidence_quote,
    )
    return {
        "status": "superseded",
        "old_record_id": rid,
        "new_record_id": new_rec.id,
        "new_pill": new_rec.pill,
    }


@router.post("/projects/{pid}/records/{rid}/retract")
async def retract_governed_record(pid: str, rid: str, body: RetractRecordRequest, db: DBSession):
    """Retract an obsolete or erroneous record (RC-4)."""
    project_or_404(db, pid)
    rec = await mem_service.retract(db=db, record_id=rid, reason=body.reason)
    return {"status": "retracted", "record_id": rec.id, "pill": rec.pill}


@router.get("/projects/{pid}/timeline")
def get_project_timeline(pid: str, db: DBSession, limit: int = 50):
    """Fetch unified chronological timeline of records, sessions, and audits (MT-1)."""
    project_or_404(db, pid)
    return timeline_service.get_timeline(db, pid, limit=limit)


@router.get("/projects/{pid}/metrics")
async def get_project_metrics(pid: str, db: DBSession):
    """Fetch authoritative §20 governance metrics, distributions, and compliance score (MT-1)."""
    project_or_404(db, pid)
    return await metrics_service.get_project_metrics(db, pid)


@router.post("/projects/{pid}/seed")
async def seed_project_data(pid: str, body: SeedRequest, db: DBSession):
    """Seed authentic ApexCart or LedgerLite enterprise memories into project (RC-6, RC-7)."""
    project_or_404(db, pid)
    return await seed_service.seed_dataset(db, pid, dataset=body.dataset)


@router.post("/projects/{pid}/outbox/flush")
async def flush_project_outbox(pid: str, db: DBSession):
    """Flush pending offline outbox messages to Hindsight Cloud (RC-5)."""
    project_or_404(db, pid)
    return await mem_service.flush_outbox(db, pid)


