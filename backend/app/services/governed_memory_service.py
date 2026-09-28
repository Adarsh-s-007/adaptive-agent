"""Governed memory lifecycle service: create, outbox, 5-step supersession, retract (RC-1, RC-2)."""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, AppErrorCode
from app.core.ids import generate_record_pill, generate_uuidv7
from app.core.memory_conventions import build_tags, render_record_content
from app.db.governed_models import MemoryRecord, RecordEvidence
from app.gateways.hindsight_gateway import HindsightGateway
from app.gateways.project_context import BankResolver


class GovernedMemoryService:
    """Manages the lifecycle of approved engineering records as the system of record."""

    def __init__(self, gateway: HindsightGateway | None = None) -> None:
        self.gateway = gateway or HindsightGateway()

    def count_active(self, db: Session, project_id: str) -> int:
        """Count active records for zero-memory short-circuit (R3)."""
        count = db.scalar(
            select(func.count())
            .select_from(MemoryRecord)
            .where(MemoryRecord.project_id == project_id, MemoryRecord.status == "active")
        )
        return count or 0

    def active_status_map(self, db: Session, project_id: str, record_ids: list[str]) -> dict[str, str]:
        """Fetch status mapping for recall post-filter."""
        if not record_ids:
            return {}
        rows = db.execute(
            select(MemoryRecord.id, MemoryRecord.status)
            .where(MemoryRecord.project_id == project_id, MemoryRecord.id.in_(record_ids))
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

    async def create_record(
        self,
        db: Session,
        project_id: str,
        title: str,
        statement: str,
        memory_type: str,
        rationale: str | None = None,
        area: str | None = None,
        importance: int = 3,
        source_session_id: str | None = None,
        evidence_quote: str | None = None,
        tags: list[str] | None = None,
        check_patterns: list[str] | None = None,
    ) -> MemoryRecord:
        """Create a governed memory record using the Outbox pattern (RC-1)."""
        ctx = BankResolver.resolve(db, project_id)
        record_id = generate_uuidv7()
        pill = generate_record_pill(record_id)
        doc_id = f"mem_{record_id}"

        record = MemoryRecord(
            id=record_id,
            pill=pill,
            project_id=project_id,
            type=memory_type,
            title=title,
            statement=statement,
            rationale=rationale,
            area=area,
            importance=importance,
            status="active",
            confidence_band="high",
            tags_json=json.dumps(tags or []),
            metadata_json=json.dumps({"area": area or "", "stated_by": "human"}),
            hindsight_document_id=doc_id,
            retain_state="pending",
            check_patterns_json=json.dumps(check_patterns or []),
        )
        db.add(record)

        if evidence_quote:
            evidence = RecordEvidence(
                record_id=record_id,
                source_session_id=source_session_id,
                quote=evidence_quote,
            )
            db.add(evidence)

        # Commit pending state to database first (Outbox pattern)
        db.commit()
        db.refresh(record)

        # Render canonical content template
        rendered_content = render_record_content(
            title=title,
            statement=statement,
            memory_type=memory_type,
            rationale=rationale,
            area=area,
        )

        # Retain via gateway
        try:
            await self.gateway.retain_record(
                ctx=ctx,
                record_id=record_id,
                content=rendered_content,
                memory_type=memory_type,
                area=area,
                importance=importance,
                source_session_id=source_session_id,
                tags=tags,
            )
            record.retain_state = "retained"
        except Exception as exc:
            record.retain_state = "failed"
            record.last_error = str(exc)
            # Enqueue to Outbox table for recovery sync (RC-5)
            from app.db.governed_models import OutboxMessage
            db.add(
                OutboxMessage(
                    project_id=project_id,
                    record_id=record_id,
                    operation="retain",
                    payload_json=json.dumps({
                        "content": rendered_content,
                        "type": memory_type,
                        "area": area,
                        "importance": importance,
                        "tags": tags or [],
                    }),
                    status="pending",
                    last_error=str(exc),
                )
            )

        db.commit()
        db.refresh(record)
        return record

    async def supersede(
        self,
        db: Session,
        old_record_id: str,
        title: str,
        statement: str,
        rationale: str | None = None,
        area: str | None = None,
        importance: int = 3,
        source_session_id: str | None = None,
        evidence_quote: str | None = None,
    ) -> MemoryRecord:
        """Execute the 5-step supersession protocol (§8.2, RC-2)."""
        old_record = db.get(MemoryRecord, old_record_id)
        if not old_record:
            raise AppError(code=AppErrorCode.NOT_FOUND, message="Record to supersede not found.", status_code=404)
        if old_record.status != "active":
            raise AppError(code=AppErrorCode.CONFLICT, message="Cannot supersede a non-active record.", status_code=409)

        ctx = BankResolver.resolve(db, old_record.project_id)
        new_record_id = generate_uuidv7()
        new_pill = generate_record_pill(new_record_id)
        doc_id = f"mem_{new_record_id}"

        # 1. Step 1: Create new record as pending
        new_record = MemoryRecord(
            id=new_record_id,
            pill=new_pill,
            project_id=old_record.project_id,
            type=old_record.type,
            title=title,
            statement=statement,
            rationale=rationale,
            area=area or old_record.area,
            importance=importance,
            status="active",
            confidence_band="high",
            hindsight_document_id=doc_id,
            retain_state="pending",
            supersedes_id=old_record.id,
        )
        db.add(new_record)

        if evidence_quote:
            db.add(RecordEvidence(record_id=new_record_id, quote=evidence_quote, source_session_id=source_session_id))

        # 2. Step 2 & 3: Mark old record superseded in DB and link
        old_record.status = "superseded"
        old_record.superseded_by_id = new_record_id
        db.commit()

        # 3. Retag old record in Hindsight to exclude it from active recall
        old_tags = build_tags(
            project_id=ctx.project_id,
            memory_type=old_record.type,
            area=old_record.area,
            status="superseded",
        )
        await self.gateway.retag_document(ctx, old_record.id, old_tags)

        # 4. Retain new record with supersedes reference
        rendered = render_record_content(
            title=title,
            statement=statement,
            memory_type=old_record.type,
            rationale=rationale,
            area=area or old_record.area,
            supersedes_ref=f"{old_record.pill} ({old_record.title})",
        )

        try:
            await self.gateway.retain_record(
                ctx=ctx,
                record_id=new_record_id,
                content=rendered,
                memory_type=old_record.type,
                area=area or old_record.area,
                importance=importance,
                source_session_id=source_session_id,
                supersedes=old_record.id,
            )
            new_record.retain_state = "retained"
        except Exception as exc:
            new_record.retain_state = "failed"
            new_record.last_error = str(exc)

        db.commit()
        db.refresh(new_record)
        return new_record

    async def retract(self, db: Session, record_id: str, reason: str | None = None) -> MemoryRecord:
        """Retract an invalid or obsolete record (RC-2)."""
        record = db.get(MemoryRecord, record_id)
        if not record:
            raise AppError(code=AppErrorCode.NOT_FOUND, message="Record not found.", status_code=404)

        ctx = BankResolver.resolve(db, record.project_id)
        record.status = "retracted"
        db.commit()

        # Retag in Hindsight
        retracted_tags = build_tags(
            project_id=ctx.project_id,
            memory_type=record.type,
            area=record.area,
            status="retracted",
        )
        await self.gateway.retag_document(ctx, record.id, retracted_tags)
        return record

    async def flush_outbox(self, db: Session, project_id: str) -> dict[str, Any]:
        """Process pending outbox messages and sync to Hindsight Cloud (RC-5)."""
        from app.db.governed_models import OutboxMessage

        ctx = BankResolver.resolve(db, project_id)
        pending = list(
            db.scalars(
                select(OutboxMessage)
                .where(OutboxMessage.project_id == project_id, OutboxMessage.status == "pending")
                .order_by(OutboxMessage.created_at.asc())
            ).all()
        )

        synced = 0
        failed = 0
        for msg in pending:
            try:
                payload = json.loads(msg.payload_json)
                if msg.operation == "retain":
                    await self.gateway.retain_record(
                        ctx=ctx,
                        record_id=msg.record_id,
                        content=payload["content"],
                        memory_type=payload["type"],
                        area=payload.get("area"),
                        importance=payload.get("importance", 3),
                        tags=payload.get("tags"),
                    )
                    rec = db.get(MemoryRecord, msg.record_id)
                    if rec:
                        rec.retain_state = "retained"
                elif msg.operation == "retag":
                    ok = await self.gateway.retag_document(ctx, msg.record_id, payload["tags"])
                    if not ok:
                        raise AppError(code=AppErrorCode.HINDSIGHT_UNAVAILABLE, message="Retag failed", status_code=502)
                msg.status = "sent"
                synced += 1
            except Exception as exc:
                msg.retry_count += 1
                msg.last_error = str(exc)
                failed += 1

        db.commit()
        return {
            "project_id": project_id,
            "messages_processed": len(pending),
            "synced": synced,
            "failed": failed,
        }
