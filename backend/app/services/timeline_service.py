"""Unified chronological timeline service for ProjectPulse (§18, MT-1).

Aggregates governed memory records, supersessions, agent sessions, candidate qualifications,
and verification activities into an authoritative audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.governed_models import CheckRun, MemoryCandidate, MemoryRecord, TaskRun
from app.models.entities import AgentSession, MemoryEvent


@dataclass
class TimelineItem:
    id: str
    event_type: str  # memory_retained, memory_superseded, memory_retracted, session_imported, candidate_approved, check_completed
    timestamp: str
    title: str
    summary: str
    pill: str | None = None
    record_id: str | None = None
    session_id: str | None = None
    actor: str = "System"
    metadata: dict[str, Any] = field(default_factory=dict)


class TimelineService:
    """Aggregates multi-source events into a unified chronological stream."""

    @staticmethod
    def get_timeline(db: Session, project_id: str, limit: int = 50) -> list[dict[str, Any]]:
        items: list[TimelineItem] = []

        # 1. Governed Memory Records (Retained, Superseded, Retracted)
        records = db.scalars(
            select(MemoryRecord)
            .where(MemoryRecord.project_id == project_id)
            .order_by(MemoryRecord.created_at.desc())
            .limit(limit)
        ).all()

        for rec in records:
            # Creation / Retain event
            items.append(
                TimelineItem(
                    id=f"evt_rec_{rec.id}",
                    event_type="memory_retained" if rec.status != "retracted" else "memory_retracted",
                    timestamp=rec.created_at.isoformat(),
                    title=f"Memory Retained: {rec.title}",
                    summary=rec.statement[:160] + ("..." if len(rec.statement) > 160 else ""),
                    pill=rec.pill,
                    record_id=rec.id,
                    actor="Human Reviewer" if rec.evidence else "System",
                    metadata={
                        "type": rec.type,
                        "area": rec.area,
                        "importance": rec.importance,
                        "status": rec.status,
                        "hindsight_doc": rec.hindsight_document_id,
                    },
                )
            )

            # Supersession event if record supersedes an older record
            if rec.supersedes_id:
                items.append(
                    TimelineItem(
                        id=f"evt_sup_{rec.id}",
                        event_type="memory_superseded",
                        timestamp=rec.updated_at.isoformat(),
                        title=f"Superseded Previous Policy ({rec.pill})",
                        summary=f"Supersedes previous decision {rec.supersedes_id[:8]} with new rule: {rec.title}",
                        pill=rec.pill,
                        record_id=rec.id,
                        actor="Architecture Review",
                        metadata={"superseded_id": rec.supersedes_id},
                    )
                )

        # 2. Agent Sessions
        sessions = db.scalars(
            select(AgentSession)
            .where(AgentSession.project_id == project_id)
            .order_by(AgentSession.created_at.desc())
            .limit(limit // 2)
        ).all()

        for sess in sessions:
            items.append(
                TimelineItem(
                    id=f"evt_sess_{sess.id}",
                    event_type="session_imported",
                    timestamp=sess.created_at.isoformat(),
                    title=f"Agent Session: {sess.task[:60]}",
                    summary=f"Imported coding session by {sess.agent_name}",
                    session_id=sess.id,
                    actor=sess.agent_name,
                    metadata={"task": sess.task},
                )
            )

        # 3. Approved Candidates in Inbox
        candidates = db.scalars(
            select(MemoryCandidate)
            .where(MemoryCandidate.project_id == project_id, MemoryCandidate.status == "approved")
            .order_by(MemoryCandidate.created_at.desc())
            .limit(limit // 2)
        ).all()

        for cand in candidates:
            items.append(
                TimelineItem(
                    id=f"evt_cand_{cand.id}",
                    event_type="candidate_approved",
                    timestamp=cand.created_at.isoformat(),
                    title=f"Candidate Approved: {cand.title[:60]}",
                    summary=cand.statement[:140],
                    session_id=cand.session_id,
                    actor="Human Reviewer",
                    metadata={"confidence": cand.confidence, "type": cand.type},
                )
            )

        # 4. Check Runs
        checks = db.scalars(
            select(CheckRun)
            .where(CheckRun.project_id == project_id)
            .order_by(CheckRun.created_at.desc())
            .limit(limit // 2)
        ).all()

        for chk in checks:
            items.append(
                TimelineItem(
                    id=f"evt_chk_{chk.id}",
                    event_type="check_completed",
                    timestamp=chk.created_at.isoformat(),
                    title=f"Memory Check: {chk.verdict.upper()}",
                    summary=f"Compliance check evaluated with verdict: {chk.verdict}",
                    actor="Memory Check Guardrail",
                    metadata={"verdict": chk.verdict, "tokens": chk.checked_tokens},
                )
            )

        # 5. Legacy memory events
        legacy_events = db.scalars(
            select(MemoryEvent)
            .where(MemoryEvent.project_id == project_id)
            .order_by(MemoryEvent.created_at.desc())
            .limit(limit // 2)
        ).all()

        for lev in legacy_events:
            items.append(
                TimelineItem(
                    id=f"evt_leg_{lev.id}",
                    event_type=f"legacy_{lev.event_type}",
                    timestamp=lev.created_at.isoformat(),
                    title=f"{lev.event_type.capitalize()} Memory Event",
                    summary=lev.source_text[:140],
                    session_id=lev.session_id,
                    actor="MCP Agent",
                    metadata={"legacy": True},
                )
            )

        # Sort all events chronologically descending
        items.sort(key=lambda x: x.timestamp, reverse=True)

        return [
            {
                "id": it.id,
                "event_type": it.event_type,
                "timestamp": it.timestamp,
                "title": it.title,
                "summary": it.summary,
                "pill": it.pill,
                "record_id": it.record_id,
                "session_id": it.session_id,
                "actor": it.actor,
                "metadata": it.metadata,
            }
            for it in items[:limit]
        ]
