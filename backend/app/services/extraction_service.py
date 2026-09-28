"""Automatic memory extraction (Blueprint §5): extraction is automatic, approval is human.

prepare → flag hints → extract (LLM, windowed) → validate (deterministic) → relate
(recall top-5 active records per candidate, classify) → queue in the Inbox.
Auto-rejected and extractor-discarded items are stored too, so the Inbox can show
"Filtered by validator (n)" with reasons. Extraction failure saves no partial candidates.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, AppErrorCode, not_found
from app.core.taxonomy import normalize_type, slugify_area
from app.db.governed_models import MemoryCandidate, MemoryRecord, SessionTurn
from app.gateways.hindsight_gateway import HindsightGateway, HindsightUnavailable
from app.gateways.llm_gateway import LLMGateway
from app.gateways.project_context import BankResolver, ProjectContext
from app.models.entities import AgentSession
from app.prompts.schemas import (
    ExtractedCandidate,
    ExtractionOutput,
    RelationItem,
    RelationOutput,
)
from app.prompts.templates import EXTRACT_SYSTEM, RELATE_SYSTEM
from app.services import heuristics
from app.services.audit_service import AuditService
from app.services.extraction_validator import ExtractionValidator, normalize_for_match
from app.services.governed_memory_service import GovernedMemoryService
from app.services.signals import TranscriptPreparer
from app.services.transcript_parser import ParsedTurn

MAX_CANDIDATES = 8


class ExtractionService:
    def __init__(
        self,
        hindsight: HindsightGateway | None = None,
        llm: LLMGateway | None = None,
        memory_service: GovernedMemoryService | None = None,
    ) -> None:
        from app.gateways.hindsight_gateway import get_hindsight_gateway
        from app.gateways.llm_gateway import get_llm_gateway

        self.hindsight = hindsight or get_hindsight_gateway()
        self.llm = llm or get_llm_gateway()
        self.memory_service = memory_service or GovernedMemoryService(self.hindsight)

    @staticmethod
    def load_turns(db: Session, session_id: str) -> list[ParsedTurn]:
        rows = db.scalars(
            select(SessionTurn).where(SessionTurn.session_id == session_id).order_by(SessionTurn.turn_index)
        ).all()
        return [ParsedTurn(role=t.role, content=t.content, turn_index=t.turn_index, speaker=t.speaker) for t in rows]

    async def extract_session(self, db: Session, project_id: str, session_id: str) -> dict[str, Any]:
        session = db.get(AgentSession, session_id)
        if not session or session.project_id != project_id:
            raise not_found("Session")
        ctx = BankResolver.resolve(db, project_id)
        started = time.perf_counter()
        turns = TranscriptPreparer.prepare_turns(self.load_turns(db, session_id))
        if not turns:
            raise AppError(AppErrorCode.VALIDATION_FAILED, "This session has no turns to extract.", status_code=422)

        # Re-running extraction replaces this session's still-unreviewed candidates.
        db.execute(
            delete(MemoryCandidate).where(
                MemoryCandidate.session_id == session_id,
                MemoryCandidate.status.in_(("pending", "auto_rejected", "filtered")),
            )
        )
        db.commit()

        hints = TranscriptPreparer.hint_turns(turns)
        extractor_model = heuristics.HEURISTIC_MODEL
        try:
            if getattr(self.llm, "configured", True):
                output = await self._llm_extract(turns, hints)
                extractor_model = getattr(self.llm, "model_small", "llm")
            else:
                output = heuristics.extract(turns, MAX_CANDIDATES)
        except AppError as exc:
            session.extraction_error = f"{exc.code}: {exc.message}"
            session.status = "closed"
            AuditService.log(db, project_id, "EXTRACT", status="error", detail={"session_id": session_id, "error": exc.message})
            db.commit()
            raise

        texts = [t.content for t in turns]
        indices = [t.turn_index for t in turns]
        roles = {t.turn_index: t.role for t in turns}
        accepted: list[tuple[ExtractedCandidate, Any]] = []
        rejected: list[tuple[ExtractedCandidate, str]] = []
        seen: set[str] = set()
        for cand in output.candidates[: MAX_CANDIDATES * 2]:
            stated_by = cand.stated_by if cand.stated_by in ("human", "agent", "both") else "human"
            verdict = ExtractionValidator.validate(
                statement=cand.statement,
                memory_type=cand.type,
                evidence_quote=cand.evidence_quote,
                transcript_texts=texts,
                stated_by=stated_by,
                initial_confidence=cand.confidence,
                turn_indices=indices,
            )
            key = normalize_for_match(cand.statement)[:120]
            if verdict.valid and key in seen:
                rejected.append((cand, "Duplicate of another candidate from this session."))
                continue
            if verdict.valid and verdict.matched_turn and roles.get(verdict.matched_turn) == "agent" and stated_by == "human":
                # The quote came from the agent: the human did not state it.
                verdict.adjusted_confidence = min(verdict.adjusted_confidence, 0.4)
                verdict.flags.append("agent_proposed")
                cand.stated_by = "agent"
            if verdict.valid:
                seen.add(key)
                accepted.append((cand, verdict))
            else:
                rejected.append((cand, verdict.reason or "Rejected by validator."))
        accepted = accepted[:MAX_CANDIDATES]

        relations, relate_mode = await self._relate(db, ctx, [c for c, _ in accepted], turns)

        created: list[MemoryCandidate] = []
        for i, (cand, verdict) in enumerate(accepted):
            rel = relations.get(i) or RelationItem(candidate_index=i, relation="new")
            target = rel.target_record_id if rel.relation != "new" else None
            if target and not db.get(MemoryRecord, target):
                target = None
            relation = rel.relation if (target or rel.relation == "new") else "new"
            candidate = MemoryCandidate(
                session_id=session_id,
                project_id=project_id,
                type=verdict.memory_type,
                title=cand.title.strip()[:120],
                statement=cand.statement.strip(),
                rationale=(cand.rationale or "").strip() or None,
                area=slugify_area(cand.area),
                applies_to_json=json.dumps(cand.applies_to[:10]),
                importance=cand.importance,
                stated_by=cand.stated_by,
                evidence_quote=cand.evidence_quote.strip(),
                evidence_turn_ids_json=json.dumps(sorted({*(cand.evidence_turn_ids or []), verdict.matched_turn or 0} - {0})),
                status="pending",
                relation=relation,
                related_record_id=target,
                relation_reason=rel.reason[:300] if rel.reason else None,
                confidence=verdict.adjusted_confidence,
                flagged=verdict.flagged,
                flags_json=json.dumps(sorted(set(verdict.flags))),
                extractor_model=extractor_model,
            )
            db.add(candidate)
            created.append(candidate)

        for cand, reason in rejected:
            db.add(
                MemoryCandidate(
                    session_id=session_id,
                    project_id=project_id,
                    type=normalize_type(cand.type),
                    title=(cand.title or cand.statement[:80]).strip()[:120],
                    statement=cand.statement.strip()[:2000],
                    evidence_quote=(cand.evidence_quote or "").strip()[:2000] or "—",
                    status="auto_rejected",
                    filter_reason=f"Validator: {reason}",
                    confidence=cand.confidence,
                    stated_by=cand.stated_by,
                    extractor_model=extractor_model,
                )
            )
        for item in output.discarded[:12]:
            db.add(
                MemoryCandidate(
                    session_id=session_id,
                    project_id=project_id,
                    type="decision",
                    title=item.item[:120],
                    statement=item.item[:2000],
                    evidence_quote="—",
                    status="auto_rejected",
                    filter_reason=f"Extractor: {item.reason}",
                    confidence=0.0,
                    extractor_model=extractor_model,
                )
            )

        latency = int((time.perf_counter() - started) * 1000)
        stats = {
            "proposed": len(output.candidates),
            "accepted": len(created),
            "auto_rejected": len(rejected),
            "discarded": len(output.discarded[:12]),
            "hint_turns": sorted(hints),
            "extractor": extractor_model,
            "relate_mode": relate_mode,
            "latency_ms": latency,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }
        session.status = "extracted"
        session.extraction_error = None
        session.extraction_stats_json = json.dumps(stats)
        if not session.ended_at:
            session.ended_at = datetime.now(timezone.utc)
        AuditService.flush(db, ctx, commit=False)
        AuditService.log(db, project_id, "EXTRACT", latency_ms=latency, detail={"session_id": session_id, **stats})
        db.commit()
        return {"session_id": session_id, "candidates": created, "stats": stats}

    # ------------------------------------------------------------------ LLM
    async def _llm_extract(self, turns: list[ParsedTurn], hints: dict[int, list[str]]) -> ExtractionOutput:
        merged = ExtractionOutput()
        for window in TranscriptPreparer.windows(turns):
            numbered = "\n\n".join(
                f"[turn {t.turn_index}] {t.role.upper()}{f' ({t.speaker})' if t.speaker else ''}:\n{t.content}"
                for t in window.turns
            )
            window_hints = {k: v for k, v in hints.items() if window.start_index <= k <= window.end_index}
            result = await self.llm.complete_json(
                tier="small",
                messages=[
                    {"role": "system", "content": EXTRACT_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"Signal hints (turn: signals) — hints only, you decide:\n{json.dumps(window_hints)}\n\n"
                            f"Transcript (data):\n<transcript>\n{numbered}\n</transcript>"
                        ),
                    },
                ],
                schema=ExtractionOutput,
                job="extract",
                temperature=0.0,
                max_tokens=3000,
            )
            parsed: ExtractionOutput = result.parsed
            merged.candidates.extend(parsed.candidates)
            merged.discarded.extend(parsed.discarded)
        return merged

    async def _relate(
        self, db: Session, ctx: ProjectContext, candidates: list[ExtractedCandidate], turns: list[ParsedTurn]
    ) -> tuple[dict[int, RelationItem], str]:
        if not candidates:
            return {}, "none"
        active = self.memory_service.get_active_records(db, ctx.project_id)
        if not active:
            return {}, "no_active_records"
        active_map = {r.id: r for r in active}
        related: dict[int, list[MemoryRecord]] = {}
        mode = "recall"
        for i, cand in enumerate(candidates):
            records: list[MemoryRecord] = []
            try:
                if not getattr(self.hindsight, "available", True):
                    raise HindsightUnavailable("offline")
                outcome = await self.hindsight.recall_detailed(
                    ctx, cand.statement, purpose="relate", max_tokens=800, budget="low", expect_results=True
                )
                for fact in outcome.facts:
                    for rid in fact.record_ids or [fact.record_id]:
                        rec = active_map.get(rid)
                        if rec and rec not in records:
                            records.append(rec)
            except (HindsightUnavailable, AppError):
                mode = "local_similarity"
                scored = sorted(
                    active,
                    key=lambda r: -len(heuristics.tokens(r.statement) & heuristics.tokens(cand.statement)),
                )
                records = scored[:5]
            related[i] = records[:5]
        AuditService.flush(db, ctx, commit=False)

        transcript_text = "\n".join(t.content for t in turns if t.role != "tool")
        if not getattr(self.llm, "configured", True):
            out = {}
            for i, cand in enumerate(candidates):
                item = heuristics.relate(cand.statement, related.get(i, []), transcript_text)
                item.candidate_index = i
                out[i] = item
            return out, f"{mode}+heuristic"

        payload = [
            {
                "candidate_index": i,
                "statement": cand.statement,
                "existing_records": [
                    {"record_id": r.id, "rule": r.statement[:400], "decided": r.decided_at.date().isoformat()}
                    for r in related.get(i, [])
                ],
            }
            for i, cand in enumerate(candidates)
        ]
        try:
            result = await self.llm.complete_json(
                tier="small",
                messages=[
                    {"role": "system", "content": RELATE_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"Transcript excerpt for context (data):\n{transcript_text[-6000:]}\n\n"
                            f"Candidates with related active records (data):\n{json.dumps(payload, ensure_ascii=False)}"
                        ),
                    },
                ],
                schema=RelationOutput,
                job="relate",
                temperature=0.0,
                max_tokens=1500,
            )
        except AppError:
            out = {}
            for i, cand in enumerate(candidates):
                item = heuristics.relate(cand.statement, related.get(i, []), transcript_text)
                item.candidate_index = i
                out[i] = item
            return out, f"{mode}+heuristic_fallback"
        parsed: RelationOutput = result.parsed
        out: dict[int, RelationItem] = {}
        for item in parsed.relations:
            if item.relation not in ("new", "duplicate", "refines", "conflicts", "supersedes"):
                item.relation = "new"
            allowed = {r.id for r in related.get(item.candidate_index, [])}
            if item.target_record_id not in allowed:
                item.target_record_id = None
                if item.relation != "new":
                    item.relation = "new"
            out[item.candidate_index] = item
        return out, f"{mode}+llm"
