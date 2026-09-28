"""Governed record lifecycle: create, outbox retain, supersede, retract, retry, reconcile (§6, §8).

PostgreSQL is written first (retain_state=pending), then Hindsight. A failed retain leaves
the record `failed` with a next_retry_at; the retry worker drives it to `retained`.
Retired records are retagged in Hindsight; until the retag succeeds the record stays
`retag_pending` and the recall post-filter excludes it by PostgreSQL status.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import AppError, AppErrorCode, conflict, invalid, not_found
from app.core.ids import generate_record_pill, generate_uuidv7
from app.core.memory_conventions import build_tags, render_record_content
from app.core.secrets import contains_secret
from app.core.taxonomy import (
    confidence_band as band_for,
)
from app.core.taxonomy import (
    default_importance,
    is_known_type,
    normalize_type,
    slugify_area,
)
from app.db.governed_models import MemoryRecord, OutboxMessage, RecordEvidence
from app.gateways.hindsight_gateway import HindsightGateway, HindsightUnavailable
from app.gateways.project_context import BankResolver, ProjectContext
from app.models.entities import AgentSession
from app.services.audit_service import AuditService
from app.services.extraction_validator import INSTRUCTION_LIKE

IDENTIFIER_RE = r"(__[A-Za-z][\w-]+|[A-Za-z_]+\.[A-Za-z_][\w.]*|X-[\w-]+|@[\w/.-]+|[a-z]+_[a-z_]+|[A-Z][a-z]+[A-Z]\w+)"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _entities(*texts: str | None) -> list[str]:
    import re

    found: list[str] = []
    for text in texts:
        for match in re.findall(IDENTIFIER_RE, text or ""):
            token = match.strip(".")
            if 3 <= len(token) <= 60 and token not in found:
                found.append(token)
    return found[:10]


class GovernedMemoryService:
    """Manages approved engineering records as the governance system of record."""

    def __init__(self, gateway: HindsightGateway | None = None) -> None:
        from app.gateways.hindsight_gateway import get_hindsight_gateway

        self.gateway = gateway or get_hindsight_gateway()
        self.settings = get_settings()

    # ------------------------------------------------------------------ reads
    def count_active(self, db: Session, project_id: str) -> int:
        return int(
            db.scalar(
                select(func.count())
                .select_from(MemoryRecord)
                .where(MemoryRecord.project_id == project_id, MemoryRecord.status == "active")
            )
            or 0
        )

    def active_status_map(self, db: Session, project_id: str, record_ids: list[str]) -> dict[str, str]:
        if not record_ids:
            return {}
        rows = db.execute(
            select(MemoryRecord.id, MemoryRecord.status).where(
                MemoryRecord.project_id == project_id, MemoryRecord.id.in_(record_ids)
            )
        ).all()
        return {r[0]: r[1] for r in rows}

    def get_records(self, db: Session, record_ids: list[str]) -> list[MemoryRecord]:
        if not record_ids:
            return []
        return list(db.scalars(select(MemoryRecord).where(MemoryRecord.id.in_(record_ids))).all())

    def get_active_records(self, db: Session, project_id: str) -> list[MemoryRecord]:
        return list(
            db.scalars(
                select(MemoryRecord)
                .where(MemoryRecord.project_id == project_id, MemoryRecord.status == "active")
                .order_by(MemoryRecord.importance.desc(), MemoryRecord.decided_at.desc())
            ).all()
        )

    def get_record(self, db: Session, project_id: str, record_id: str) -> MemoryRecord:
        record = db.get(MemoryRecord, record_id)
        if not record or record.project_id != project_id:
            raise not_found("Record")
        return record

    # -------------------------------------------------------------- validation
    @staticmethod
    def validate_fields(title: str, statement: str, memory_type: str, rationale: str | None) -> None:
        if not is_known_type(memory_type):
            raise invalid(f"Unknown memory type '{memory_type}'.")
        if not title or len(title.strip()) < 3:
            raise invalid("Title must be at least 3 characters.")
        if len(statement.strip()) < 15:
            raise invalid("Statement must be at least 15 characters.")
        for text in (title, statement, rationale or ""):
            if contains_secret(text):
                raise invalid("Records must not contain secrets or credentials.")
            if INSTRUCTION_LIKE.search(text):
                raise invalid(
                    "Record text contains instruction-like content. Rephrase it as an engineering rule."
                )

    # ------------------------------------------------------------------ create
    async def create_record(
        self,
        db: Session,
        project_id: str,
        title: str,
        statement: str,
        memory_type: str,
        rationale: str | None = None,
        area: str | None = None,
        importance: int | None = None,
        source_session_id: str | None = None,
        evidence_quote: str | None = None,
        tags: list[str] | None = None,
        check_patterns: list[str] | None = None,
        *,
        applies_to: list[str] | None = None,
        decided_at: datetime | None = None,
        confidence: float = 1.0,
        stated_by: str = "human",
        source: str = "manual",
        candidate_id: str | None = None,
        approved_by: str | None = None,
        evidence_turn: int | None = None,
        supersedes_record: MemoryRecord | None = None,
        retain_async: bool = False,
        commit_retain: bool = True,
    ) -> MemoryRecord:
        ctx = BankResolver.resolve(db, project_id)
        self.validate_fields(title, statement, memory_type, rationale)
        memory_type_norm = normalize_type(memory_type)
        band = band_for(confidence)
        decided = decided_at or _now()
        if decided.tzinfo is None:
            decided = decided.replace(tzinfo=timezone.utc)
        record_id = generate_uuidv7()
        area_slug = slugify_area(area)
        if not check_patterns:
            from app.services.heuristics import derive_patterns

            check_patterns = derive_patterns(statement)
        extra_tags = [t for t in (tags or []) if t]
        record = MemoryRecord(
            id=record_id,
            pill=generate_record_pill(record_id),
            project_id=project_id,
            type=memory_type_norm,
            title=title.strip()[:255],
            statement=statement.strip(),
            rationale=(rationale or "").strip() or None,
            area=area_slug,
            applies_to_json=json.dumps([a.strip() for a in (applies_to or []) if a and a.strip()][:12]),
            importance=max(1, min(3, importance or default_importance(memory_type_norm))),
            status="active",
            confidence=confidence,
            confidence_band=band,
            tentative=band == "low",
            stated_by=stated_by,
            source=source,
            decided_at=decided,
            tags_json=json.dumps(extra_tags),
            hindsight_document_id=f"mem_{record_id}",
            retain_state="pending",
            check_patterns_json=json.dumps(check_patterns or []),
            supersedes_id=supersedes_record.id if supersedes_record else None,
            candidate_id=candidate_id,
            source_session_id=source_session_id,
            approved_by=approved_by or ("seed" if source == "seed" else None),
            approved_at=_now(),
            review_due_at=decided + timedelta(days=self.settings.review_due_days),
        )
        session_title = None
        if source_session_id:
            session = db.get(AgentSession, source_session_id)
            session_title = session.title or session.task if session else None
        supersedes_ref = None
        if supersedes_record is not None:
            supersedes_ref = (
                f"{supersedes_record.decided_at.date().isoformat()}: {supersedes_record.statement}"
            )
        record.retained_content = render_record_content(
            title=record.title,
            statement=record.statement,
            memory_type=memory_type_norm,
            rationale=record.rationale,
            area=area_slug,
            supersedes_ref=supersedes_ref,
            project_name=ctx.project_name,
            applies_to=json.loads(record.applies_to_json),
            decided_at=decided,
            session_title=session_title,
            decided_by=approved_by,
        )
        record.metadata_json = json.dumps(
            {
                "record_id": record_id,
                "project_id": project_id,
                "type": memory_type_norm,
                "area": area_slug or "",
                "stated_by": stated_by,
                "source": source,
            }
        )
        db.add(record)
        if evidence_quote:
            db.add(
                RecordEvidence(
                    record_id=record_id,
                    source_session_id=source_session_id,
                    quote=evidence_quote.strip(),
                    speaker=stated_by if stated_by in ("human", "agent") else "human",
                    turn_index=evidence_turn,
                )
            )
        AuditService.log(
            db,
            project_id,
            "RECORD_CREATED",
            record_id=record_id,
            actor=approved_by,
            detail={"pill": record.pill, "type": memory_type_norm, "source": source, "title": record.title},
        )
        db.commit()
        db.refresh(record)

        if commit_retain:
            await self._retain(db, ctx, record, async_=retain_async)
        return record

    def _tags_for(self, ctx: ProjectContext, record: MemoryRecord, status: str | None = None) -> list[str]:
        return build_tags(
            ctx.project_id,
            normalize_type(record.type),
            area=record.area,
            status=status or record.status,
            confidence_band=record.confidence_band,
            extra_tags=json.loads(record.tags_json or "[]"),
        )

    async def _retain(
        self, db: Session, ctx: ProjectContext, record: MemoryRecord, *, async_: bool = False
    ) -> bool:
        """Push one record to Hindsight. Never raises; failures become outbox state."""
        if not getattr(self.gateway, "available", True):
            # Hindsight offline: keep the approval, mark it "waiting to sync".
            record.retain_state = "pending"
            record.last_error = "Hindsight unavailable; queued for sync."
            db.commit()
            return False
        content =record.retained_content or render_record_content(
            title=record.title,
            statement=record.statement,
            memory_type=normalize_type(record.type),
            rationale=record.rationale,
            area=record.area,
            project_name=ctx.project_name,
            decided_at=record.decided_at,
        )
        try:
            await self.gateway.retain_record(
                ctx=ctx,
                record_id=record.id,
                content=content,
                memory_type=normalize_type(record.type),
                area=record.area,
                importance=record.importance,
                source_session_id=record.source_session_id,
                supersedes=record.supersedes_id,
                stated_by=record.stated_by,
                async_=async_,
                project_id=record.project_id,
                decided_at=record.decided_at,
                status=record.status,
                confidence_band=record.confidence_band,
                entities=_entities(record.statement, record.title),
                record_tags=self._tags_for(ctx, record),
            )
        except Exception as exc:  # noqa: BLE001 - any failure is queued for retry
            record.retain_state = "failed"
            record.retry_count = (record.retry_count or 0) + 1
            record.last_error = getattr(exc, "message", str(exc))[:1000]
            record.next_retry_at = _now() + self._backoff(record.retry_count)
            AuditService.flush(db, ctx, commit=False)
            db.commit()
            return False
        record.retain_state = "retained"
        record.last_error = None
        record.next_retry_at = None
        AuditService.flush(db, ctx, commit=False)
        db.commit()
        return True

    @staticmethod
    def _backoff(attempt: int) -> timedelta:
        return timedelta(seconds=min(30 * (2 ** max(0, attempt - 1)), 3600) + random.uniform(0, 5))

    def add_evidence(
        self,
        db: Session,
        record: MemoryRecord,
        *,
        session_id: str | None,
        quote: str,
        speaker: str = "human",
        turn_index: int | None = None,
    ) -> RecordEvidence:
        evidence = RecordEvidence(
            record_id=record.id,
            source_session_id=session_id,
            quote=quote.strip(),
            speaker=speaker if speaker in ("human", "agent") else "human",
            turn_index=turn_index,
        )
        db.add(evidence)
        AuditService.log(db, record.project_id, "EVIDENCE_ADDED", record_id=record.id, detail={"session_id": session_id})
        db.commit()
        return evidence

    # --------------------------------------------------------------- supersede
    async def supersede(
        self,
        db: Session,
        old_record_id: str,
        title: str,
        statement: str,
        rationale: str | None = None,
        area: str | None = None,
        importance: int | None = None,
        source_session_id: str | None = None,
        evidence_quote: str | None = None,
        *,
        memory_type: str | None = None,
        applies_to: list[str] | None = None,
        approved_by: str | None = None,
        decided_at: datetime | None = None,
        candidate_id: str | None = None,
        confidence: float = 1.0,
        stated_by: str = "human",
        source: str = "manual",
        check_patterns: list[str] | None = None,
        evidence_turn: int | None = None,
        project_id: str | None = None,
    ) -> MemoryRecord:
        """§8.2: create B (active, supersedes A) → retag A superseded → update A in PostgreSQL."""
        old = db.get(MemoryRecord, old_record_id)
        if not old or (project_id and old.project_id != project_id):
            raise not_found("Record to supersede")
        if old.status != "active":
            raise conflict(f"{old.pill} is {old.status}; only active records can be superseded.")

        new = await self.create_record(
            db,
            old.project_id,
            title=title,
            statement=statement,
            memory_type=memory_type or old.type,
            rationale=rationale,
            area=area or old.area,
            importance=importance or old.importance,
            source_session_id=source_session_id,
            evidence_quote=evidence_quote,
            check_patterns=check_patterns if check_patterns is not None else json.loads(old.check_patterns_json or "[]"),
            applies_to=applies_to if applies_to is not None else json.loads(old.applies_to_json or "[]"),
            decided_at=decided_at,
            confidence=confidence,
            stated_by=stated_by,
            source=source,
            candidate_id=candidate_id,
            approved_by=approved_by,
            evidence_turn=evidence_turn,
            supersedes_record=old,
        )

        ctx = BankResolver.resolve(db, old.project_id)
        old.status = "superseded"
        old.superseded_by_id = new.id
        old.retired_at = _now()
        old.retain_state = "retag_pending"
        AuditService.log(
            db,
            old.project_id,
            "SUPERSEDE",
            record_id=old.id,
            actor=approved_by,
            detail={"old_pill": old.pill, "new_pill": new.pill, "new_record_id": new.id},
        )
        db.commit()
        await self._retag(db, ctx, old)
        db.refresh(new)
        return new

    async def _retag(self, db: Session, ctx: ProjectContext, record: MemoryRecord) -> bool:
        ok = False
        try:
            ok = await self.gateway.update_document_tags(ctx, record.id, self._tags_for(ctx, record))
        except Exception as exc:  # noqa: BLE001
            record.last_error = getattr(exc, "message", str(exc))[:1000]
        if ok:
            record.retain_state = "retained"
            record.last_error = None
            record.next_retry_at = None
        else:
            record.retain_state = "retag_pending"
            record.retry_count = (record.retry_count or 0) + 1
            record.next_retry_at = _now() + self._backoff(record.retry_count)
        AuditService.flush(db, ctx, commit=False)
        db.commit()
        return ok

    # ----------------------------------------------------------------- retract
    async def retract(
        self,
        db: Session,
        record_id: str,
        reason: str | None = None,
        reviewer: str | None = None,
        project_id: str | None = None,
    ) -> MemoryRecord:
        record = db.get(MemoryRecord, record_id)
        if not record or (project_id and record.project_id != project_id):
            raise not_found("Record")
        if record.status != "active":
            raise conflict(f"{record.pill} is already {record.status}.")
        ctx = BankResolver.resolve(db, record.project_id)
        record.status = "retracted"
        record.retired_at = _now()
        record.retract_reason = (reason or "").strip() or None
        record.retain_state = "retag_pending"
        AuditService.log(
            db, record.project_id, "RETRACT", record_id=record.id, actor=reviewer, detail={"reason": reason}
        )
        db.commit()
        await self._retag(db, ctx, record)
        return record

    # ------------------------------------------------------------------- retry
    async def retry(self, db: Session, record: MemoryRecord) -> MemoryRecord:
        ctx = BankResolver.resolve(db, record.project_id)
        if record.retain_state in ("pending", "failed"):
            await self._retain(db, ctx, record)
        elif record.retain_state == "retag_pending":
            await self._retag(db, ctx, record)
        db.refresh(record)
        return record

    async def process_outbox(
        self, db: Session, project_id: str | None = None, *, limit: int = 50, force: bool = False
    ) -> dict[str, Any]:
        """Retry records whose Hindsight write is outstanding (worker + manual flush)."""
        if not self.gateway.available:
            return {"processed": 0, "synced": 0, "failed": 0, "skipped": "hindsight_unavailable"}
        now = _now()
        query = select(MemoryRecord).where(
            MemoryRecord.retain_state.in_(("pending", "failed", "retag_pending"))
        )
        if project_id:
            query = query.where(MemoryRecord.project_id == project_id)
        if not force:
            query = query.where(
                MemoryRecord.retry_count < self.settings.retry_max_attempts,
                or_(MemoryRecord.next_retry_at.is_(None), MemoryRecord.next_retry_at <= now),
            )
        records = list(db.scalars(query.order_by(MemoryRecord.created_at).limit(limit)).all())
        synced = failed = 0
        for record in records:
            await self.retry(db, record)
            if record.retain_state == "retained":
                synced += 1
            else:
                failed += 1

        legacy_query = select(OutboxMessage).where(OutboxMessage.status == "pending")
        if project_id:
            legacy_query = legacy_query.where(OutboxMessage.project_id == project_id)
        legacy = list(db.scalars(legacy_query).all())
        for message in legacy:
            record = db.get(MemoryRecord, message.record_id)
            if record and record.retain_state == "retained":
                message.status = "sent"
        db.commit()
        return {"processed": len(records), "synced": synced, "failed": failed}

    async def flush_outbox(self, db: Session, project_id: str) -> dict[str, Any]:
        result = await self.process_outbox(db, project_id, force=True)
        return {
            "project_id": project_id,
            "messages_processed": result.get("processed", 0),
            "synced": result.get("synced", 0),
            "failed": result.get("failed", 0),
            **({"skipped": result["skipped"]} if "skipped" in result else {}),
        }

    async def reconcile(self, db: Session, project_id: str | None = None) -> int:
        """Heal records whose retain reached Hindsight but whose DB update was lost (§18)."""
        if not self.gateway.available:
            return 0
        query = select(MemoryRecord).where(MemoryRecord.retain_state.in_(("pending", "failed")))
        if project_id:
            query = query.where(MemoryRecord.project_id == project_id)
        healed = 0
        for record in db.scalars(query.limit(100)).all():
            ctx = BankResolver.resolve(db, record.project_id)
            try:
                doc = await self.gateway.get_document(ctx, record.id)
            except HindsightUnavailable:
                continue
            if doc and f"status:{record.status}" in (doc.get("tags") or []):
                record.retain_state = "retained"
                record.last_error = None
                healed += 1
        if healed:
            db.commit()
        return healed

    def require_record_project(self, db: Session, project_id: str, record_id: str) -> MemoryRecord:
        record = db.get(MemoryRecord, record_id)
        if not record or record.project_id != project_id:
            raise AppError(AppErrorCode.NOT_FOUND, "Record not found.", status_code=404)
        return record
