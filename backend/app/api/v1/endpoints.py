"""/api/v1 routers (Blueprint §13.3). Routers validate and delegate; they never call Hindsight or the LLM."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import AppError, AppErrorCode, not_found
from app.core.ratelimit import llm_rate_limit
from app.core.security import require_demo_mode, verify_bearer_token
from app.db.database import get_db
from app.db.governed_models import (
    AuditEvent,
    CheckRun,
    ComparisonRun,
    EvalRun,
    MemoryCandidate,
    MemoryRecord,
    SessionTurn,
    TaskRun,
)
from app.gateways.hindsight_gateway import HindsightUnavailable
from app.gateways.project_context import context_for, get_project
from app.services.audit_service import AuditService
from app.services.container import services
from app.services.eval_service import EvalService
from app.services.seed_service import demo_tasks
from app.services.serializers import (
    candidate_dto,
    check_dto,
    comparison_dto,
    iso,
    loads,
    project_dto,
    record_dto,
    record_ref,
    run_dto,
    session_dto,
)

from .schemas import (
    ApproveBody,
    AskBody,
    BriefBody,
    BulkApproveBody,
    CheckBody,
    CloseBody,
    CompareBody,
    DatasetBody,
    EvalBody,
    ImportBody,
    MessageBody,
    OfflineBody,
    ProjectCreateBody,
    RecordCreateBody,
    RejectBody,
    RememberBody,
    RetractBody,
    ReviewBody,
    RunBody,
    SeedBody,
    SessionCreateBody,
    SupersedeBody,
)

router = APIRouter(dependencies=[Depends(verify_bearer_token)])
DB = Annotated[Session, Depends(get_db)]
RateLimited = [Depends(llm_rate_limit)]


# =============================================================== status / projects
@router.get("/status", tags=["health"])
async def status():
    svc = services()
    hindsight = await svc.hindsight.health()
    llm = await svc.llm.health()
    settings = get_settings()
    return {
        "hindsight": hindsight,
        "llm": llm,
        "demo_mode": settings.demo_mode,
        "force_offline": svc.hindsight.is_forced_offline,
        "auth_required": bool(settings.app_access_token),
        "models": {"large": settings.llm_model_large, "small": settings.llm_model_small},
        "empty_recall_retries": svc.hindsight.stats.get("empty_recall_retries", 0),
    }


@router.get("/demo-tasks", tags=["demo"])
def get_demo_tasks():
    return demo_tasks()


@router.post("/projects", status_code=201, tags=["projects"])
async def create_project(body: ProjectCreateBody, db: DB):
    svc = services()
    project = await svc.projects.create_project(db, body.name, body.description, body.tech_stack, body.areas)
    return project_dto(project, svc.projects.stats(db, project.id))


@router.get("/projects", tags=["projects"])
def list_projects(db: DB):
    return services().projects.list_projects(db)


@router.get("/projects/{pid}", tags=["projects"])
def project_detail(pid: str, db: DB):
    return services().projects.detail(db, pid)


@router.post("/projects/{pid}/provision", tags=["projects"])
async def provision_project(pid: str, db: DB, force: bool = False):
    project = await services().projects.provision_project(db, pid, force=force)
    return {
        "project_id": project.id,
        "bank_id": project.hindsight_bank_id,
        "bank_status": project.bank_status,
        "bank_error": project.bank_error,
    }


@router.get("/projects/{pid}/bank", tags=["projects"])
async def bank_summary(pid: str, db: DB):
    return await services().projects.bank_summary(db, pid)


# ======================================================================= sessions
@router.post("/projects/{pid}/sessions", status_code=201, tags=["sessions"])
def create_session(pid: str, body: SessionCreateBody, db: DB):
    session = services().sessions.create(
        db, pid, title=body.title, developer=body.developer, agent_label=body.agent_label
    )
    return session_dto(session, turns=[])


@router.get("/projects/{pid}/sessions", tags=["sessions"])
def list_sessions(pid: str, db: DB, include_legacy: bool = False):
    return services().sessions.list(db, pid, include_legacy=include_legacy)


@router.post("/projects/{pid}/sessions/import", status_code=201, tags=["sessions"])
async def import_session(pid: str, body: ImportBody, db: DB):
    svc = services()
    session = svc.sessions.import_transcript(
        db,
        pid,
        title=body.title,
        text=body.body,
        developer=body.developer,
        agent_label=body.agent_label,
        occurred_at=body.occurred_at,
        format_hint=body.fmt,
    )
    result: dict[str, Any] = {
        "session_id": session.id,
        "session": session_dto(session),
        "turns_imported": session.turn_count,
        "candidates_extracted": 0,
        "message": "Session imported. End it or run extraction to propose memory.",
    }
    if body.extract:
        extracted = await svc.extraction.extract_session(db, pid, session.id)
        result["candidates_extracted"] = len(extracted["candidates"])
        result["stats"] = extracted["stats"]
        result["message"] = "Session imported and extracted. Candidates await review in the Inbox."
    return result


@router.get("/projects/{pid}/sessions/{sid}", tags=["sessions"])
def session_detail(pid: str, sid: str, db: DB):
    svc = services()
    data = svc.sessions.detail(db, pid, sid)
    runs = {
        r.id: r
        for r in db.scalars(select(TaskRun).where(TaskRun.session_id == sid)).all()
    }
    for turn in data.get("turns", []):
        if turn.get("run_id") and turn["run_id"] in runs:
            run = runs[turn["run_id"]]
            turn["run"] = {
                "id": run.id,
                "mode": run.mode,
                "brief": loads(run.brief_snapshot_json, None),
                "recall_ms": run.recall_ms,
                "filter_ms": run.filter_ms,
                "llm_ms": run.llm_ms,
                "injected_tokens": run.injected_tokens,
                "files": loads(run.output_files_json, []),
                "notes": loads(run.output_notes_json, []),
                "followed_record_ids": loads(run.followed_record_ids_json, []),
                "model": run.model,
            }
    data["candidates"] = [
        candidate_dto(c)
        for c in db.scalars(select(MemoryCandidate).where(MemoryCandidate.session_id == sid)).all()
    ]
    return data


@router.post("/projects/{pid}/sessions/{sid}/messages", dependencies=RateLimited, tags=["sessions"])
async def send_message(pid: str, sid: str, body: MessageBody, db: DB):
    return await services().sessions.send_message(
        db, pid, sid, content=body.content, use_memory=body.use_memory, file_paths=body.file_paths
    )


@router.post("/projects/{pid}/sessions/{sid}/close", dependencies=RateLimited, tags=["sessions"])
async def close_session(pid: str, sid: str, db: DB, body: CloseBody | None = None):
    svc = services()
    session = svc.sessions.close(db, pid, sid)
    result: dict[str, Any] = {"session": session_dto(session), "candidates": [], "filtered": []}
    if body is None or body.extract:
        extracted = await svc.extraction.extract_session(db, pid, sid)
        db.refresh(session)
        result.update(_extraction_payload(db, pid, sid, extracted))
        result["session"] = session_dto(session)
    return result


def _extraction_payload(db: Session, pid: str, sid: str, extracted: dict[str, Any]) -> dict[str, Any]:
    rows = db.scalars(select(MemoryCandidate).where(MemoryCandidate.session_id == sid)).all()
    related = {
        r.id: r
        for r in db.scalars(
            select(MemoryRecord).where(MemoryRecord.id.in_([c.related_record_id for c in rows if c.related_record_id]))
        ).all()
    }
    return {
        "candidates": [candidate_dto(c, related.get(c.related_record_id)) for c in rows if c.status == "pending"],
        "filtered": [candidate_dto(c) for c in rows if c.status in ("auto_rejected", "filtered")],
        "stats": extracted.get("stats", {}),
    }


@router.post("/projects/{pid}/sessions/{sid}/extract", dependencies=RateLimited, tags=["sessions"])
async def extract_session(pid: str, sid: str, db: DB):
    extracted = await services().extraction.extract_session(db, pid, sid)
    return _extraction_payload(db, pid, sid, extracted)


@router.post("/projects/{pid}/sessions/{sid}/turns/{tid}/remember", status_code=201, tags=["sessions"])
async def remember_turn(pid: str, sid: str, tid: str, body: RememberBody, db: DB):
    """“Remember this”: a human-authored record (confidence 1.0) with the turn as evidence."""
    svc = services()
    session = svc.sessions.get(db, pid, sid)
    turn = db.get(SessionTurn, tid)
    if not turn or turn.session_id != session.id:
        raise not_found("Turn")
    quote = (body.quote or turn.content[:400]).strip()
    if quote not in turn.content:
        raise AppError(AppErrorCode.VALIDATION_FAILED, "The quote must be copied from the message.", status_code=422)
    record = await svc.memory.create_record(
        db,
        pid,
        title=body.title,
        statement=body.statement,
        memory_type=body.type,
        rationale=body.rationale,
        area=body.area,
        source_session_id=session.id,
        evidence_quote=quote,
        confidence=1.0,
        stated_by="human",
        source="manual",
        approved_by=body.reviewer,
        evidence_turn=turn.turn_index,
    )
    return record_dto(record, include_content=True)


# ===================================================================== candidates
def _candidate_list(db: Session, pid: str, status: str | None) -> list[dict[str, Any]]:
    svc = services()
    get_project(db, pid)
    rows = svc.review.list_candidates(db, pid, status)
    related = {
        r.id: r
        for r in db.scalars(
            select(MemoryRecord).where(MemoryRecord.id.in_([c.related_record_id for c in rows if c.related_record_id]))
        ).all()
    }
    return [candidate_dto(c, related.get(c.related_record_id)) for c in rows]


@router.get("/projects/{pid}/candidates", tags=["inbox"])
def list_candidates(pid: str, db: DB, status: str = "pending"):
    return _candidate_list(db, pid, status)


@router.get("/projects/{pid}/inbox", tags=["inbox"])
def inbox(pid: str, db: DB):
    """Candidates grouped by source session, with the filtered rows and yield counts."""
    items = _candidate_list(db, pid, "all")
    sessions: dict[str, dict[str, Any]] = {}
    from app.models.entities import AgentSession

    for item in items:
        group = sessions.get(item["session_id"])
        if group is None:
            s = db.get(AgentSession, item["session_id"])
            group = {
                "session": session_dto(s) if s else {"id": item["session_id"], "title": "Session"},
                "pending": [],
                "filtered": [],
                "reviewed": [],
            }
            sessions[item["session_id"]] = group
        if item["status"] == "pending":
            group["pending"].append(item)
        elif item["status"] == "auto_rejected":
            group["filtered"].append(item)
        else:
            group["reviewed"].append(item)
    groups = sorted(
        sessions.values(),
        key=lambda g: (-len(g["pending"]), g["session"].get("occurred_at") or ""),
    )
    return {
        "groups": [g for g in groups if g["pending"] or g["filtered"]],
        "counts": {
            "pending": sum(len(g["pending"]) for g in groups),
            "filtered": sum(len(g["filtered"]) for g in groups),
            "reviewed": sum(len(g["reviewed"]) for g in groups),
        },
    }


def _approval_response(result: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "approved", "resolution": result.get("resolution")}
    record = result.get("record")
    if record is not None:
        out["record"] = record_dto(record)
        out["id"] = record.id
    if result.get("superseded_record") is not None:
        out["superseded_record"] = record_dto(result["superseded_record"])
    if result.get("evidence_id"):
        out["evidence_id"] = result["evidence_id"]
    return out


@router.post("/projects/{pid}/candidates/{cid}/approve", tags=["inbox"])
async def approve_candidate(pid: str, cid: str, body: ApproveBody, db: DB):
    result = await services().review.approve_candidate(
        db,
        cid,
        body.resolution,
        body.target_record_id,
        reviewer=body.reviewer,
        project_id=pid,
        edits=body.edits,
    )
    return _approval_response(result)


@router.post("/projects/{pid}/candidates/{cid}/reject", tags=["inbox"])
def reject_candidate(pid: str, cid: str, body: RejectBody, db: DB):
    candidate = services().review.reject_candidate(db, cid, body.reason, body.reviewer, project_id=pid)
    return candidate_dto(candidate)


@router.post("/projects/{pid}/candidates/{cid}/review", tags=["inbox"])
async def review_candidate(pid: str, cid: str, body: ReviewBody, db: DB):
    """Legacy combined endpoint: resolution=reject | new | supersede | keep_both | add_evidence."""
    svc = services()
    if body.resolution == "reject":
        candidate = svc.review.reject_candidate(db, cid, "Rejected during review.", body.reviewer, project_id=pid)
        return {"status": "rejected", "candidate_id": candidate.id}
    result = await svc.review.approve_candidate(
        db,
        cid,
        body.resolution,
        body.target_record_id,
        body.edited_title,
        body.edited_statement,
        body.reviewer,
        project_id=pid,
    )
    return _approval_response(result)


@router.post("/projects/{pid}/candidates/approve-high-confidence", tags=["inbox"])
async def approve_high_confidence(pid: str, body: BulkApproveBody, db: DB):
    results = await services().review.approve_high_confidence(db, pid, body.reviewer)
    return {"approved": len(results), "records": [record_dto(r["record"]) for r in results if r.get("record")]}


# ======================================================================= memories
def _list_records(db: Session, pid: str, status: str | None, type_: str | None, area: str | None, q: str | None):
    get_project(db, pid)
    query = select(MemoryRecord).where(MemoryRecord.project_id == pid)
    if status and status != "all":
        query = query.where(MemoryRecord.status == status)
    if type_:
        query = query.where(MemoryRecord.type == type_)
    if area:
        query = query.where(MemoryRecord.area == area)
    records = db.scalars(query.order_by(MemoryRecord.decided_at.desc())).all()
    if q:
        needle = q.lower()
        records = [r for r in records if needle in r.title.lower() or needle in r.statement.lower() or needle in r.pill.lower()]
    return [record_dto(r) for r in records]


@router.get("/projects/{pid}/memories", tags=["memory"])
def list_memories(
    pid: str,
    db: DB,
    status: str | None = "active",
    type: str | None = None,
    area: str | None = None,
    q: str | None = None,
):
    """Library browsing in PostgreSQL (admin only — never used for agent recall)."""
    return _list_records(db, pid, status, type, area, q)


@router.get("/projects/{pid}/records", tags=["memory"], include_in_schema=False)
def list_records_alias(
    pid: str, db: DB, status: str | None = None, memory_type: str | None = None, area: str | None = None
):
    return _list_records(db, pid, status, memory_type, area, None)


async def _record_detail(db: Session, pid: str, rid: str) -> dict[str, Any]:
    svc = services()
    record = svc.memory.get_record(db, pid, rid)
    data = record_dto(record, include_content=True)
    chain: list[dict[str, Any]] = []
    cursor = record
    seen = {record.id}
    while cursor.supersedes_id and cursor.supersedes_id not in seen:
        prev = db.get(MemoryRecord, cursor.supersedes_id)
        if not prev:
            break
        chain.append(record_ref(prev) | {"relation": "older"})
        seen.add(prev.id)
        cursor = prev
    newer: list[dict[str, Any]] = []
    cursor = record
    while cursor.superseded_by_id and cursor.superseded_by_id not in seen:
        nxt = db.get(MemoryRecord, cursor.superseded_by_id)
        if not nxt:
            break
        newer.append(record_ref(nxt) | {"relation": "newer"})
        seen.add(nxt.id)
        cursor = nxt
    data["version_chain"] = list(reversed(newer)) + [record_ref(record) | {"relation": "this"}] + chain

    applied_runs = []
    for run in db.scalars(
        select(TaskRun)
        .where(TaskRun.project_id == pid, TaskRun.mode == "memory")
        .order_by(TaskRun.created_at.desc())
        .limit(200)
    ).all():
        brief = loads(run.brief_snapshot_json, {}) or {}
        if any((a.get("record") or {}).get("id") == rid for a in brief.get("applied") or []):
            applied_runs.append({"run_id": run.id, "task": run.task[:140], "created_at": iso(run.created_at)})
    violated = []
    for check in db.scalars(
        select(CheckRun).where(CheckRun.project_id == pid).order_by(CheckRun.created_at.desc()).limit(300)
    ).all():
        for v in loads(check.violations_json, []):
            if v.get("record_id") == rid:
                violated.append(
                    {"check_id": check.id, "run_id": check.run_id, "excerpt": v.get("excerpt"), "created_at": iso(check.created_at)}
                )
    data["applied_in"] = applied_runs[:20]
    data["violated_in"] = violated[:20]
    if record.source_session_id:
        from app.models.entities import AgentSession

        session = db.get(AgentSession, record.source_session_id)
        if session:
            data["source_session"] = session_dto(session)
    data["hindsight_document"] = None
    if svc.hindsight.available:
        try:
            ctx = context_for(get_project(db, pid))
            doc = await svc.hindsight.get_document(ctx, record.id)
            AuditService.flush(db, ctx)
            if doc:
                data["hindsight_document"] = {
                    "id": doc.get("id"),
                    "tags": doc.get("tags"),
                    "memory_unit_count": doc.get("memory_unit_count"),
                    "nodes_by_fact_type": doc.get("nodes_by_fact_type"),
                    "updated_at": doc.get("updated_at"),
                }
        except HindsightUnavailable:
            pass
    return data


@router.get("/projects/{pid}/memories/{rid}", tags=["memory"])
async def memory_detail(pid: str, rid: str, db: DB):
    return await _record_detail(db, pid, rid)


@router.get("/projects/{pid}/records/{rid}", tags=["memory"], include_in_schema=False)
async def record_detail_alias(pid: str, rid: str, db: DB):
    return await _record_detail(db, pid, rid)


async def _create_record(pid: str, body: RecordCreateBody, db: Session) -> dict[str, Any]:
    record = await services().memory.create_record(
        db,
        pid,
        title=body.title,
        statement=body.statement,
        memory_type=body.kind,
        rationale=body.rationale,
        area=body.area,
        importance=body.importance3,
        evidence_quote=body.evidence_quote,
        tags=body.tags,
        check_patterns=body.check_patterns,
        applies_to=body.applies_to,
        decided_at=body.decided_at,
        source=body.source,
        approved_by=body.reviewer,
    )
    return record_dto(record)


@router.post("/projects/{pid}/memories", status_code=201, tags=["memory"])
async def create_memory(pid: str, body: RecordCreateBody, db: DB):
    return await _create_record(pid, body, db)


@router.post("/projects/{pid}/records", status_code=201, tags=["memory"], include_in_schema=False)
async def create_record_alias(pid: str, body: RecordCreateBody, db: DB):
    return await _create_record(pid, body, db)


async def _supersede(pid: str, rid: str, body: SupersedeBody, db: Session) -> dict[str, Any]:
    svc = services()
    new = await svc.memory.supersede(
        db,
        rid,
        title=body.title,
        statement=body.statement,
        rationale=body.rationale,
        area=body.area,
        importance=min(3, body.importance) if body.importance else None,
        evidence_quote=body.evidence_quote,
        memory_type=body.type,
        applies_to=body.applies_to,
        approved_by=body.reviewer,
        project_id=pid,
    )
    old = db.get(MemoryRecord, rid)
    return {
        "record": record_dto(new),
        "superseded_record": record_dto(old) if old else None,
        # Legacy keys.
        "status": "superseded",
        "old_record_id": rid,
        "new_record_id": new.id,
        "new_pill": new.pill,
        **record_dto(new),
    }


@router.post("/projects/{pid}/memories/{rid}/supersede", tags=["memory"])
async def supersede_memory(pid: str, rid: str, body: SupersedeBody, db: DB):
    return await _supersede(pid, rid, body, db)


@router.post("/projects/{pid}/records/{rid}/supersede", tags=["memory"], include_in_schema=False)
async def supersede_record_alias(pid: str, rid: str, body: SupersedeBody, db: DB):
    return await _supersede(pid, rid, body, db)


@router.post("/projects/{pid}/memories/{rid}/retract", tags=["memory"])
async def retract_memory(pid: str, rid: str, db: DB, body: RetractBody | None = None):
    body = body or RetractBody()
    record = await services().memory.retract(db, rid, body.reason, body.reviewer, project_id=pid)
    return {**record_dto(record), "record_id": record.id}


@router.post("/projects/{pid}/records/{rid}/retract", tags=["memory"], include_in_schema=False)
async def retract_record_alias(pid: str, rid: str, db: DB, body: RetractBody | None = None):
    return await retract_memory(pid, rid, db, body)


@router.post("/projects/{pid}/memories/{rid}/retry", tags=["memory"])
async def retry_memory(pid: str, rid: str, db: DB):
    svc = services()
    record = svc.memory.get_record(db, pid, rid)
    record = await svc.memory.retry(db, record)
    return record_dto(record)


@router.post("/projects/{pid}/outbox/flush", tags=["memory"])
async def flush_outbox(pid: str, db: DB):
    get_project(db, pid)
    return await services().memory.flush_outbox(db, pid)


# ======================================================== brief / runs / compare
@router.post("/projects/{pid}/brief", dependencies=RateLimited, tags=["agent"])
async def brief(pid: str, body: BriefBody, db: DB):
    result = await services().brief.build_brief(db, pid, body.task, body.file_paths)
    return result.model_dump()


@router.post("/projects/{pid}/runs", dependencies=RateLimited, tags=["agent"])
async def create_run(pid: str, body: RunBody, db: DB):
    svc = services()
    get_project(db, pid)
    if not getattr(svc.llm, "configured", True):
        raise AppError(AppErrorCode.LLM_UNAVAILABLE, "Runs need an LLM. Set GROQ_API_KEY on the server.", status_code=503)
    brief_result = None
    if body.mode == "memory":
        brief_result = await svc.brief.build_brief(db, pid, body.task, body.file_paths)
        if brief_result.status == "memory_unavailable":
            raise AppError(
                AppErrorCode.HINDSIGHT_UNAVAILABLE,
                brief_result.message or "Memory is unavailable; run in baseline mode instead.",
                status_code=503,
            )
    run = await svc.generation.run(db, pid, body.task, body.mode, body.session_id, brief=brief_result)
    return run.model_dump()


@router.get("/projects/{pid}/runs", tags=["agent"])
def list_runs(pid: str, db: DB, limit: int = Query(30, le=100)):
    get_project(db, pid)
    runs = db.scalars(
        select(TaskRun).where(TaskRun.project_id == pid).order_by(TaskRun.created_at.desc()).limit(limit)
    ).all()
    return [run_dto(r) for r in runs]


@router.get("/projects/{pid}/runs/{run_id}", tags=["agent"])
def run_detail(pid: str, run_id: str, db: DB):
    run = db.get(TaskRun, run_id)
    if not run or run.project_id != pid:
        raise not_found("Run")
    data = run_dto(run)
    check = db.scalars(select(CheckRun).where(CheckRun.run_id == run_id).order_by(CheckRun.created_at.desc())).first()
    data["check"] = check_dto(check) if check else None
    return data


@router.post("/projects/{pid}/compare", tags=["agent"], dependencies=RateLimited)
async def start_compare(pid: str, body: CompareBody, db: DB, wait: bool = False):
    svc = services()
    get_project(db, pid)
    if wait:
        result = await svc.compare.compare(db, pid, body.task, body.repeats)
        return result.model_dump()
    comparison = svc.compare.start(db, pid, body.task, body.repeats)
    return {"comparison_id": comparison.id, **comparison_dto(comparison)}


@router.get("/projects/{pid}/compare", tags=["agent"])
def list_comparisons(pid: str, db: DB, limit: int = Query(20, le=50)):
    get_project(db, pid)
    rows = db.scalars(
        select(ComparisonRun).where(ComparisonRun.project_id == pid).order_by(ComparisonRun.created_at.desc()).limit(limit)
    ).all()
    return [comparison_dto(r) for r in rows]


@router.get("/projects/{pid}/compare/{cid}", tags=["agent"])
async def get_compare(pid: str, cid: str, request: Request, db: DB):
    svc = services()
    if "text/event-stream" not in request.headers.get("accept", ""):
        return svc.compare.load(db, pid, cid).model_dump()
    row = db.get(ComparisonRun, cid)
    if not row or row.project_id != pid:
        raise not_found("Comparison")
    factory = svc.compare.session_factory

    async def events():
        last_stage = None
        for _ in range(1200):  # ~10 minutes max
            if await request.is_disconnected():
                return
            with factory() as session:
                current = session.get(ComparisonRun, cid)
                stage, state = current.stage, current.status
                if stage != last_stage:
                    last_stage = stage
                    payload: dict[str, Any] = {"stage": stage, "status": state}
                    if state in ("completed", "failed"):
                        payload["result"] = svc.compare.load(session, pid, cid).model_dump()
                    yield f"event: {stage}\ndata: {json.dumps(payload, default=str)}\n\n"
                if state in ("completed", "failed"):
                    return
            yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/projects/{pid}/check", dependencies=RateLimited, tags=["agent"])
async def memory_check(pid: str, body: CheckBody, db: DB):
    result = await services().check.check(db, pid, body.content, body.run_id)
    return result.model_dump()


@router.get("/projects/{pid}/checks", tags=["agent"])
def list_checks(pid: str, db: DB, limit: int = Query(20, le=100)):
    get_project(db, pid)
    rows = db.scalars(
        select(CheckRun).where(CheckRun.project_id == pid).order_by(CheckRun.created_at.desc()).limit(limit)
    ).all()
    return [check_dto(c) for c in rows]


# ======================================================================= reflect
@router.post("/projects/{pid}/ask", dependencies=RateLimited, tags=["reflect"])
async def ask(pid: str, body: AskBody, db: DB):
    return await services().reflect.ask(db, pid, body.question)


@router.get("/projects/{pid}/rulebook", tags=["reflect"])
async def rulebook(pid: str, db: DB):
    return await services().reflect.get_rulebook(db, pid)


@router.post("/projects/{pid}/rulebook/refresh", tags=["reflect"])
async def rulebook_refresh(pid: str, db: DB):
    return await services().reflect.refresh_rulebook(db, pid)


@router.get("/projects/{pid}/rulebook/history", tags=["reflect"])
async def rulebook_history(pid: str, db: DB):
    return await services().reflect.history(db, pid)


@router.get("/projects/{pid}/rulebook/export", tags=["reflect"])
def rulebook_export(pid: str, db: DB, format: str = "claude_md"):
    return services().reflect.export(db, pid, "cursorrules" if format == "cursorrules" else "claude_md")


# ============================================================ timeline / metrics
@router.get("/projects/{pid}/timeline", tags=["insights"])
def timeline(pid: str, db: DB, limit: int = Query(100, le=300)):
    get_project(db, pid)
    return services().timeline.get_timeline(db, pid, limit=limit)


@router.get("/projects/{pid}/metrics", tags=["insights"])
async def metrics(pid: str, db: DB):
    get_project(db, pid)
    return await services().metrics.get_project_metrics(db, pid)


@router.get("/projects/{pid}/audit", tags=["insights"])
def audit(pid: str, db: DB, type: str | None = None, limit: int = Query(100, le=500)):
    get_project(db, pid)
    query = select(AuditEvent).where(AuditEvent.project_id == pid)
    if type:
        query = query.where(AuditEvent.event_type == type)
    rows = db.scalars(query.order_by(AuditEvent.created_at.desc()).limit(limit)).all()
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "status": e.status,
            "latency_ms": e.latency_ms,
            "record_id": e.record_id,
            "run_id": e.run_id,
            "actor": e.actor,
            "detail": loads(e.detail_json, {}),
            "created_at": iso(e.created_at),
        }
        for e in rows
    ]


@router.post("/projects/{pid}/eval", dependencies=RateLimited, tags=["insights"])
async def run_eval(pid: str, db: DB, body: EvalBody | None = None):
    return await services().eval.run(db, pid, (body or EvalBody()).set)


@router.get("/projects/{pid}/eval", tags=["insights"])
def list_evals(pid: str, db: DB):
    get_project(db, pid)
    rows = db.scalars(
        select(EvalRun).where(EvalRun.project_id == pid).order_by(EvalRun.created_at.desc()).limit(10)
    ).all()
    return [EvalService.dto(r) for r in rows]


# ========================================================================= admin
@router.post("/admin/seed", dependencies=[Depends(require_demo_mode)], tags=["admin"])
async def admin_seed(body: SeedBody, db: DB):
    return await services().seed.seed(db, body.project, reset=body.reset)


@router.post("/projects/{pid}/seed", dependencies=[Depends(require_demo_mode)], tags=["admin"])
async def seed_project(pid: str, body: DatasetBody, db: DB):
    return await services().seed.seed_dataset(db, pid, body.dataset)


@router.post("/projects/{pid}/reset", dependencies=[Depends(require_demo_mode)], tags=["admin"])
async def reset_project(pid: str, db: DB):
    project = get_project(db, pid)
    await services().seed.reset_project(db, project)
    return {"status": "reset", "project_id": pid}


@router.get("/admin/hindsight/offline", tags=["admin"])
def get_offline():
    return {"force_offline": services().hindsight.is_forced_offline}


@router.post("/admin/hindsight/offline", dependencies=[Depends(require_demo_mode)], tags=["admin"])
def set_offline(body: OfflineBody):
    services().hindsight.set_force_offline(body.force_offline)
    return {"force_offline": services().hindsight.is_forced_offline}
