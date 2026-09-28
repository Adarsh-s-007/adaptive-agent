"""Governed memory records: create/retain (outbox), supersede, retract, evidence. Owner: P3.

Public functions (contract C-7) used by other owners:
  create_record, supersede, retract, add_evidence, retry,
  active_status_map, count_active, get_records, to_ref, to_out

Rule: records are immutable after approval. An edit is a superseding version.
The DB transaction is committed before every Hindsight call (outbox pattern).
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_event
from app.core.errors import AppError, ErrorCode
from app.core.ids import record_pill, uuid7
from app.core.memory_conventions import document_id
from app.db.models import MemoryRecord, Project, RecordEvidence
from app.gateways.hindsight_gateway import HindsightGateway, get_hindsight_gateway
from app.gateways.project_context import ProjectContext, resolve
from app.schemas.common import MemoryRecordOut, RecordRef, confidence_band
from app.schemas.memories import RecordCreate
from app.services.record_template import build_document, tags_for

REVIEW_AFTER = timedelta(days=180)
SEED_NAMESPACE = uuid.UUID("9b1f0c52-6a0e-4d7e-9a57-2f3c1c0b7e11")
SECRET_PATTERN = re.compile(
    r"(?:hsk_|gsk_|sk-[A-Za-z0-9]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?:password|api[_-]?key|secret)\s*[:=]\s*\S+|postgres(?:ql)?://\S+:\S+@)",
    re.IGNORECASE,
)


def _gateway(gateway: HindsightGateway | None) -> HindsightGateway:
    return gateway or get_hindsight_gateway()


def to_ref(record: MemoryRecord) -> RecordRef:
    return RecordRef(
        id=record.id,
        pill=record_pill(record.id),
        type=record.type,
        title=record.title,
        statement=record.statement,
        area=record.area,
        importance=record.importance,
        status=record.status,
        confidence_band=confidence_band(record.confidence),
        decided_at=record.decided_at,
        tentative=record.confidence < 0.4,
    )


def to_out(record: MemoryRecord, evidence_count: int = 1) -> MemoryRecordOut:
    return MemoryRecordOut(
        **to_ref(record).model_dump(),
        project_id=record.project_id,
        rationale=record.rationale,
        applies_to=record.applies_to,
        confidence=record.confidence,
        stated_by=record.stated_by,
        source_session_id=record.source_session_id,
        evidence_quote=record.evidence_quote,
        evidence_turn_ids=record.evidence_turn_ids,
        supersedes_record_id=record.supersedes_record_id,
        superseded_by_record_id=record.superseded_by_record_id,
        hindsight_document_id=record.hindsight_document_id,
        retain_state=record.retain_state,
        source=record.source,
        approved_by=record.approved_by,
        approved_at=record.approved_at,
        review_due_at=record.review_due_at,
        evidence_count=evidence_count,
    )


async def _project_name(db: AsyncSession, ctx: ProjectContext) -> str:
    project = await db.get(Project, ctx.project_id)
    return project.name if project else ctx.name


async def _retain(
    db: AsyncSession,
    ctx: ProjectContext,
    record: MemoryRecord,
    gateway: HindsightGateway,
    replaces: MemoryRecord | None = None,
) -> None:
    """Push one record to Hindsight and record the outcome. Never raises for provider errors."""
    doc = build_document(record, await _project_name(db, ctx), replaces)
    started = time.perf_counter()
    record.retain_attempts += 1
    try:
        await gateway.retain_record(ctx, doc)
        record.retain_state = "retained"
        record.last_error = None
        status = "ok"
    except AppError as exc:
        if exc.code == ErrorCode.NOT_IMPLEMENTED:
            raise
        record.retain_state = "failed"
        record.last_error = f"{exc.code}: {exc.message}"
        status = "error"
    await record_event(
        db,
        project_id=ctx.project_id,
        event_type="RETAIN",
        status=status,
        latency_ms=int((time.perf_counter() - started) * 1000),
        record_id=record.id,
        detail={"document_id": record.hindsight_document_id, "error": record.last_error},
    )
    await db.commit()


def _validate(body: RecordCreate) -> None:
    for text in (body.statement, body.rationale or "", body.evidence_quote or ""):
        if SECRET_PATTERN.search(text):
            raise AppError(ErrorCode.VALIDATION_FAILED, "Records must not contain secrets.")


async def create_record(
    db: AsyncSession,
    project_id: uuid.UUID,
    body: RecordCreate,
    *,
    candidate_id: uuid.UUID | None = None,
    supersedes: MemoryRecord | None = None,
    gateway: HindsightGateway | None = None,
) -> MemoryRecord:
    """Persist as pending, commit, then retain synchronously. A failed retain leaves the
    record visible with retain_state=failed so it can be retried."""
    ctx = await resolve(db, project_id)
    _validate(body)
    record_id = (
        uuid.uuid5(SEED_NAMESPACE, f"{project_id}:{body.seed_key}") if body.seed_key else None
    )
    if record_id is not None:
        existing = await db.get(MemoryRecord, record_id)
        if existing is not None:
            return existing
    now = datetime.now(UTC)
    record = MemoryRecord(
        project_id=ctx.project_id,
        type=body.type,
        title=body.title,
        statement=body.statement,
        rationale=body.rationale,
        area=body.area,
        applies_to=body.applies_to,
        importance=body.importance,
        status="active",
        confidence=body.confidence,
        stated_by=body.stated_by,
        decided_at=body.decided_at or now,
        source_session_id=body.source_session_id,
        evidence_quote=body.evidence_quote,
        supersedes_record_id=supersedes.id if supersedes else None,
        retain_state="pending",
        check_patterns=body.check_patterns,
        source=body.source,
        candidate_id=candidate_id,
        approved_by=body.approved_by,
        approved_at=now,
        review_due_at=(body.decided_at or now) + REVIEW_AFTER,
    )
    record.id = record_id or uuid7()
    record.hindsight_document_id = document_id(record.id)
    db.add(record)
    await db.commit()
    await _retain(db, ctx, record, _gateway(gateway), replaces=supersedes)
    return record


async def _retag(
    db: AsyncSession,
    ctx: ProjectContext,
    record: MemoryRecord,
    gateway: HindsightGateway,
    event: str,
) -> None:
    started = time.perf_counter()
    try:
        await gateway.retag(ctx, str(record.id), tags_for(record))
        if record.retain_state == "retag_pending":
            record.retain_state = "retained"
        status, error = "ok", None
    except AppError as exc:
        if exc.code == ErrorCode.NOT_IMPLEMENTED:
            raise
        # Recall post-filters by PostgreSQL status, so the record stays excluded meanwhile.
        record.retain_state = "retag_pending"
        record.last_error = f"{exc.code}: {exc.message}"
        status, error = "error", record.last_error
    await record_event(
        db,
        project_id=ctx.project_id,
        event_type=event,
        status=status,
        latency_ms=int((time.perf_counter() - started) * 1000),
        record_id=record.id,
        detail={"error": error},
    )
    await db.commit()


async def get_record(db: AsyncSession, project_id: uuid.UUID, record_id: uuid.UUID) -> MemoryRecord:
    record = await db.get(MemoryRecord, record_id)
    if record is None or record.project_id != project_id:
        raise AppError(ErrorCode.NOT_FOUND, "Record not found.")
    return record


async def supersede(
    db: AsyncSession,
    project_id: uuid.UUID,
    old_id: uuid.UUID,
    body: RecordCreate,
    *,
    reviewer: str,
    candidate_id: uuid.UUID | None = None,
    gateway: HindsightGateway | None = None,
) -> tuple[MemoryRecord, MemoryRecord]:
    """Blueprint 8.2: new active record -> retag old -> mark old superseded."""
    gw = _gateway(gateway)
    old = await get_record(db, project_id, old_id)
    if old.status != "active":
        raise AppError(ErrorCode.CONFLICT, f"Record is already {old.status}.")
    body = body.model_copy(update={"approved_by": reviewer})
    new = await create_record(
        db, project_id, body, candidate_id=candidate_id, supersedes=old, gateway=gw
    )
    old.status = "superseded"
    old.superseded_by_record_id = new.id
    await db.commit()
    ctx = await resolve(db, project_id)
    await _retag(db, ctx, old, gw, "SUPERSEDE")
    return new, old


async def retract(
    db: AsyncSession,
    project_id: uuid.UUID,
    record_id: uuid.UUID,
    *,
    reviewer: str,
    reason: str,
    gateway: HindsightGateway | None = None,
) -> MemoryRecord:
    record = await get_record(db, project_id, record_id)
    if record.status != "active":
        raise AppError(ErrorCode.CONFLICT, f"Record is already {record.status}.")
    record.status = "retracted"
    record.last_error = None
    await db.commit()
    ctx = await resolve(db, project_id)
    await _retag(db, ctx, record, _gateway(gateway), "RETRACT")
    await record_event(
        db,
        project_id=project_id,
        event_type="RETRACT_REASON",
        record_id=record.id,
        detail={"reviewer": reviewer, "reason": reason},
    )
    await db.commit()
    return record


async def retry(
    db: AsyncSession,
    project_id: uuid.UUID,
    record_id: uuid.UUID,
    *,
    gateway: HindsightGateway | None = None,
) -> MemoryRecord:
    gw = _gateway(gateway)
    record = await get_record(db, project_id, record_id)
    ctx = await resolve(db, project_id)
    if record.retain_state in ("pending", "failed"):
        replaces = (
            await db.get(MemoryRecord, record.supersedes_record_id)
            if record.supersedes_record_id
            else None
        )
        await _retain(db, ctx, record, gw, replaces)
    elif record.retain_state == "retag_pending":
        await _retag(db, ctx, record, gw, "RETAG")
    return record


async def add_evidence(
    db: AsyncSession, record_id: uuid.UUID, *, session_id: uuid.UUID | None, quote: str
) -> RecordEvidence:
    """Duplicate candidates add provenance to an existing record; nothing is retained."""
    evidence = RecordEvidence(record_id=record_id, session_id=session_id, quote=quote)
    db.add(evidence)
    await db.commit()
    return evidence


async def evidence_counts(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = await db.execute(
        select(RecordEvidence.record_id, func.count())
        .where(RecordEvidence.record_id.in_(ids))
        .group_by(RecordEvidence.record_id)
    )
    return {rid: 1 + n for rid, n in rows.all()}


async def active_status_map(
    db: AsyncSession, project_id: uuid.UUID, ids: list[str] | list[uuid.UUID]
) -> dict[str, str]:
    """record_id -> status for recall post-filtering (only this project's records)."""
    parsed = []
    for i in ids:
        try:
            parsed.append(uuid.UUID(str(i)))
        except ValueError:
            continue
    if not parsed:
        return {}
    rows = await db.execute(
        select(MemoryRecord.id, MemoryRecord.status).where(
            MemoryRecord.project_id == project_id, MemoryRecord.id.in_(parsed)
        )
    )
    return {str(rid): status for rid, status in rows.all()}


async def count_active(db: AsyncSession, project_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(MemoryRecord)
            .where(MemoryRecord.project_id == project_id, MemoryRecord.status == "active")
        )
    ) or 0


async def get_records(
    db: AsyncSession, project_id: uuid.UUID, ids: list[str]
) -> list[MemoryRecord]:
    parsed = [uuid.UUID(i) for i in ids]
    if not parsed:
        return []
    rows = await db.scalars(
        select(MemoryRecord).where(
            MemoryRecord.project_id == project_id, MemoryRecord.id.in_(parsed)
        )
    )
    return list(rows)


async def list_records(
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    type_: str | None = None,
    area: str | None = None,
    status: str | None = None,
    q: str | None = None,
) -> list[MemoryRecord]:
    """Admin browsing only. Never used for agent-facing recall."""
    stmt = select(MemoryRecord).where(MemoryRecord.project_id == project_id)
    if type_:
        stmt = stmt.where(MemoryRecord.type == type_)
    if area:
        stmt = stmt.where(MemoryRecord.area == area)
    if status:
        stmt = stmt.where(MemoryRecord.status == status)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            func.lower(MemoryRecord.title).like(like)
            | func.lower(MemoryRecord.statement).like(like)
        )
    rows = await db.scalars(stmt.order_by(MemoryRecord.decided_at.desc()).limit(500))
    return list(rows)


async def version_chain(db: AsyncSession, record: MemoryRecord) -> list[uuid.UUID]:
    """Oldest -> newest ids through supersedes / superseded_by links."""
    chain = [record]
    cur = record
    while cur.supersedes_record_id:
        cur = await db.get(MemoryRecord, cur.supersedes_record_id)
        if cur is None or cur in chain:
            break
        chain.insert(0, cur)
    cur = record
    while cur.superseded_by_record_id:
        cur = await db.get(MemoryRecord, cur.superseded_by_record_id)
        if cur is None or cur in chain:
            break
        chain.append(cur)
    return [r.id for r in chain]
