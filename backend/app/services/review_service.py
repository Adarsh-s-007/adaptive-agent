"""Memory Inbox: approve, edit-then-approve, reject and resolve relations (Blueprint §5.3, §9.5)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import conflict, invalid, not_found
from app.core.taxonomy import normalize_type
from app.db.governed_models import MemoryCandidate, MemoryRecord, RecordEvidence
from app.models.entities import AgentSession
from app.services.audit_service import AuditService
from app.services.extraction_validator import INSTRUCTION_LIKE
from app.services.governed_memory_service import GovernedMemoryService

RESOLUTIONS = ("new", "supersede", "keep_both", "add_evidence")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReviewService:
    def __init__(self, memory_service: GovernedMemoryService | None = None) -> None:
        self.memory_service = memory_service or GovernedMemoryService()

    def list_candidates(self, db: Session, project_id: str, status: str | None = "pending") -> list[MemoryCandidate]:
        query = select(MemoryCandidate).where(MemoryCandidate.project_id == project_id)
        if status == "auto_rejected":
            query = query.where(MemoryCandidate.status.in_(("auto_rejected", "filtered")))
        elif status and status != "all":
            query = query.where(MemoryCandidate.status == status)
        return list(db.scalars(query.order_by(MemoryCandidate.created_at.desc())).all())

    def get(self, db: Session, project_id: str | None, candidate_id: str) -> MemoryCandidate:
        candidate = db.get(MemoryCandidate, candidate_id)
        if not candidate or (project_id and candidate.project_id != project_id):
            raise not_found("Candidate")
        return candidate

    @staticmethod
    def default_resolution(candidate: MemoryCandidate) -> str:
        return {
            "duplicate": "add_evidence",
            "refines": "supersede",
            "supersedes": "supersede",
            "conflicts": "supersede",
        }.get(candidate.relation or "new", "new")

    async def approve_candidate(
        self,
        db: Session,
        candidate_id: str,
        resolution: str | None = None,
        target_record_id: str | None = None,
        edited_title: str | None = None,
        edited_statement: str | None = None,
        reviewer: str = "Reviewer",
        *,
        project_id: str | None = None,
        edits: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candidate = self.get(db, project_id, candidate_id)
        if candidate.status != "pending":
            raise conflict(f"Candidate is already {candidate.status}.")
        edits = {k: v for k, v in (edits or {}).items() if v not in (None, "")}
        if edited_title:
            edits["title"] = edited_title
        if edited_statement:
            edits["statement"] = edited_statement
        resolution = resolution or self.default_resolution(candidate)
        if resolution not in RESOLUTIONS:
            raise invalid(f"Unsupported resolution '{resolution}'.")

        statement = (edits.get("statement") or candidate.statement).strip()
        title = (edits.get("title") or candidate.title).strip()
        rationale = edits.get("rationale", candidate.rationale)
        # S1: instruction-like candidates cannot be approved unedited.
        if candidate.flagged and (
            "statement" not in edits or INSTRUCTION_LIKE.search(statement) or statement == candidate.statement
        ):
            raise invalid("This candidate contains instruction-like text. Edit the statement before approving it.")

        memory_type = normalize_type(edits.get("type") or candidate.type)
        area = edits.get("area", candidate.area)
        applies_to = edits.get("applies_to") or json.loads(candidate.applies_to_json or "[]")
        importance = int(edits.get("importance") or candidate.importance or 2)
        turn_ids = json.loads(candidate.evidence_turn_ids_json or "[]")
        session = db.get(AgentSession, candidate.session_id)
        decided_at = (session.occurred_at or session.created_at) if session else None
        stated_by = candidate.stated_by or "human"
        confidence = float(candidate.confidence or 0.8)
        target_id = target_record_id or candidate.related_record_id
        result: dict[str, Any] = {"resolution": resolution}

        if resolution == "add_evidence":
            target = self._target(db, candidate.project_id, target_id)
            evidence = self.memory_service.add_evidence(
                db,
                target,
                session_id=candidate.session_id,
                quote=candidate.evidence_quote,
                speaker=stated_by,
                turn_index=turn_ids[0] if turn_ids else None,
            )
            candidate.record_id = target.id
            result.update(record=target, evidence_id=evidence.id)
        elif resolution == "supersede":
            target = self._target(db, candidate.project_id, target_id)
            record = await self.memory_service.supersede(
                db,
                target.id,
                title=title,
                statement=statement,
                rationale=rationale,
                area=area,
                importance=importance,
                source_session_id=candidate.session_id,
                evidence_quote=candidate.evidence_quote,
                memory_type=memory_type,
                applies_to=applies_to,
                approved_by=reviewer,
                decided_at=decided_at,
                candidate_id=candidate.id,
                confidence=confidence,
                stated_by=stated_by,
                source="extracted",
                evidence_turn=turn_ids[0] if turn_ids else None,
            )
            db.refresh(target)
            candidate.record_id = record.id
            result.update(record=record, superseded_record=target)
        else:  # new · keep_both
            record = await self.memory_service.create_record(
                db,
                candidate.project_id,
                title=title,
                statement=statement,
                memory_type=memory_type,
                rationale=rationale,
                area=area,
                importance=importance,
                source_session_id=candidate.session_id,
                evidence_quote=candidate.evidence_quote,
                applies_to=applies_to,
                decided_at=decided_at,
                confidence=confidence,
                stated_by=stated_by,
                source="extracted",
                candidate_id=candidate.id,
                approved_by=reviewer,
                evidence_turn=turn_ids[0] if turn_ids else None,
            )
            candidate.record_id = record.id
            result.update(record=record)

        candidate.status = "approved"
        candidate.reviewed_by = reviewer
        candidate.reviewed_at = _now()
        AuditService.log(
            db,
            candidate.project_id,
            "APPROVE",
            record_id=candidate.record_id,
            actor=reviewer,
            detail={"candidate_id": candidate.id, "resolution": resolution, "edited": bool(edits)},
        )
        db.commit()
        return result

    def _target(self, db: Session, project_id: str, target_id: str | None) -> MemoryRecord:
        if not target_id:
            raise invalid("This resolution needs target_record_id.")
        target = db.get(MemoryRecord, target_id)
        if not target or target.project_id != project_id:
            raise not_found("Target record")
        return target

    def reject_candidate(
        self,
        db: Session,
        candidate_id: str,
        reason: str = "Rejected by reviewer",
        reviewer: str = "Reviewer",
        *,
        project_id: str | None = None,
    ) -> MemoryCandidate:
        candidate = self.get(db, project_id, candidate_id)
        if candidate.status != "pending":
            raise conflict(f"Candidate is already {candidate.status}.")
        candidate.status = "rejected"
        candidate.reject_reason = reason
        candidate.filter_reason = candidate.filter_reason or reason
        candidate.reviewed_by = reviewer
        candidate.reviewed_at = _now()
        AuditService.log(
            db, candidate.project_id, "REJECT", actor=reviewer, detail={"candidate_id": candidate.id, "reason": reason}
        )
        db.commit()
        db.refresh(candidate)
        return candidate

    async def approve_high_confidence(self, db: Session, project_id: str, reviewer: str) -> list[dict[str, Any]]:
        """One click: approve every pending `new`, high-confidence, unflagged candidate."""
        results = []
        for candidate in self.list_candidates(db, project_id, "pending"):
            if (candidate.relation or "new") in ("new", "unrelated") and (candidate.confidence or 0) >= 0.75 and not candidate.flagged:
                results.append(
                    await self.approve_candidate(db, candidate.id, "new", reviewer=reviewer, project_id=project_id)
                )
        return results

    @staticmethod
    def evidence_for(db: Session, record_id: str) -> list[RecordEvidence]:
        return list(db.scalars(select(RecordEvidence).where(RecordEvidence.record_id == record_id)).all())
