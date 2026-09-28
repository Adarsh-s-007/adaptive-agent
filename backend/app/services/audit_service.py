"""Persists governance/audit events produced by gateways and services (Blueprint §15.8)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.governed_models import AuditEvent
from app.gateways.project_context import ProjectContext


class AuditService:
    @staticmethod
    def log(
        db: Session,
        project_id: str | None,
        event_type: str,
        *,
        status: str = "ok",
        latency_ms: int | None = None,
        record_id: str | None = None,
        run_id: str | None = None,
        actor: str | None = None,
        detail: dict[str, Any] | None = None,
        commit: bool = False,
    ) -> AuditEvent:
        event = AuditEvent(
            project_id=project_id,
            event_type=event_type,
            status=status,
            latency_ms=latency_ms,
            record_id=record_id,
            run_id=run_id,
            actor=actor,
            detail_json=json.dumps(detail or {}, default=str)[:20000],
        )
        db.add(event)
        if commit:
            db.commit()
        return event

    @staticmethod
    def flush(db: Session, ctx: ProjectContext, *, commit: bool = True) -> int:
        """Write the gateway events accumulated on a ProjectContext."""
        count = 0
        while ctx.events:
            e = ctx.events.pop(0)
            AuditService.log(
                db,
                ctx.project_id,
                e["event_type"],
                status=e.get("status", "ok"),
                latency_ms=e.get("latency_ms"),
                record_id=e.get("record_id"),
                run_id=e.get("run_id"),
                detail=e.get("detail"),
            )
            count += 1
        if count and commit:
            db.commit()
        return count

    @staticmethod
    def isolation_violations(db: Session, project_id: str | None = None) -> int:
        query = select(func.count()).select_from(AuditEvent).where(
            AuditEvent.event_type == "ISOLATION_VIOLATION_BLOCKED"
        )
        if project_id:
            query = query.where(AuditEvent.project_id == project_id)
        return int(db.scalar(query) or 0)
