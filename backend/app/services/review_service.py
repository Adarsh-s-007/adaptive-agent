"""Memory Candidate Review Service: Approval resolutions and inbox governance (GV-1)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, AppErrorCode
from app.db.governed_models import MemoryCandidate, MemoryRecord, RecordEvidence
from app.services.governed_memory_service import GovernedMemoryService


class ReviewService:
    """Processes candidate qualification and approval into the governed system of record."""

    def __init__(self, memory_service: GovernedMemoryService | None = None) -> None:
        self.memory_service = memory_service or GovernedMemoryService()

    def list_candidates(
        self,
        db: Session,
        project_id: str,
        status: str = "pending",
    ) -> list[MemoryCandidate]:
        return list(
            db.scalars(
                select(MemoryCandidate)
                .where(MemoryCandidate.project_id == project_id, MemoryCandidate.status == status)
                .order_by(MemoryCandidate.created_at.desc())
            ).all()
        )

    async def approve_candidate(
        self,
        db: Session,
        candidate_id: str,
        resolution: str = "new",  # new, supersede, keep_both, add_evidence
        target_record_id: str | None = None,
        edited_title: str | None = None,
        edited_statement: str | None = None,
        reviewer: str = "Lead Engineer",
    ) -> MemoryRecord | RecordEvidence:
        candidate = db.get(MemoryCandidate, candidate_id)
        if not candidate:
            raise AppError(code=AppErrorCode.NOT_FOUND, message="Candidate not found.", status_code=404)
        if candidate.status != "pending":
            raise AppError(code=AppErrorCode.CONFLICT, message="Candidate has already been reviewed.", status_code=409)

        final_title = edited_title or candidate.title
        final_statement = edited_statement or candidate.statement

        # Resolution handling
        if resolution in ("new", "keep_both"):
            record = await self.memory_service.create_record(
                db=db,
                project_id=candidate.project_id,
                title=final_title,
                statement=final_statement,
                memory_type=candidate.type,
                rationale=candidate.rationale,
                area=candidate.area,
                source_session_id=candidate.session_id,
                evidence_quote=candidate.evidence_quote,
            )
            candidate.status = "approved"
            db.commit()
            return record

        elif resolution == "supersede":
            rec_to_supersede = target_record_id or candidate.related_record_id
            if not rec_to_supersede:
                raise AppError(code=AppErrorCode.VALIDATION_FAILED, message="Missing target_record_id for supersession.")

            record = await self.memory_service.supersede(
                db=db,
                old_record_id=rec_to_supersede,
                title=final_title,
                statement=final_statement,
                rationale=candidate.rationale,
                area=candidate.area,
                source_session_id=candidate.session_id,
                evidence_quote=candidate.evidence_quote,
            )
            candidate.status = "approved"
            db.commit()
            return record

        elif resolution == "add_evidence":
            rec_id = target_record_id or candidate.related_record_id
            if not rec_id:
                raise AppError(code=AppErrorCode.VALIDATION_FAILED, message="Missing target_record_id to attach evidence.")

            evidence = RecordEvidence(
                record_id=rec_id,
                source_session_id=candidate.session_id,
                quote=candidate.evidence_quote,
                speaker="human",
            )
            db.add(evidence)
            candidate.status = "approved"
            db.commit()
            return evidence

        raise AppError(code=AppErrorCode.VALIDATION_FAILED, message=f"Unsupported resolution '{resolution}'.")

    def reject_candidate(
        self,
        db: Session,
        candidate_id: str,
        reason: str = "Rejected by reviewer",
    ) -> MemoryCandidate:
        candidate = db.get(MemoryCandidate, candidate_id)
        if not candidate:
            raise AppError(code=AppErrorCode.NOT_FOUND, message="Candidate not found.", status_code=404)

        candidate.status = "rejected"
        candidate.filter_reason = reason
        db.commit()
        db.refresh(candidate)
        return candidate
