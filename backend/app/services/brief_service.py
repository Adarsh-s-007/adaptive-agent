"""Brief: recall → group by record → status post-filter → applicability → ≤5 records (§4.2).

The rendered `<project_memory>` block is the only thing that differs between a baseline
run and a memory-aware run.
"""

from __future__ import annotations

import json
import time

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.tokens import count_tokens
from app.db.governed_models import MemoryRecord
from app.gateways.hindsight_gateway import (
    BankMissing,
    HindsightGateway,
    HindsightUnavailable,
)
from app.gateways.llm_gateway import LLMGateway
from app.gateways.project_context import BankResolver, ProjectContext
from app.models.entities import Project
from app.prompts.schemas import ApplicabilityItem, ApplicabilityResponse
from app.prompts.templates import APPLICABILITY_SYSTEM
from app.schemas.common import (
    AppliedRecord,
    BriefResult,
    FilteredRecord,
    Observation,
    RecordRef,
)
from app.services import heuristics
from app.services.audit_service import AuditService
from app.services.governed_memory_service import GovernedMemoryService
from app.services.serializers import record_ref

MAX_APPLIED = 5


def ref(record: MemoryRecord) -> RecordRef:
    return RecordRef(**record_ref(record))


def render_memory_block(records: list[MemoryRecord]) -> str:
    """Layer 3 of the generation prompt: a delimited data block, fields length-capped."""
    if not records:
        return ""
    entries = []
    for r in records:
        scope = ", ".join(json.loads(r.applies_to_json or "[]")) or (r.area or "project-wide")
        lines = [
            f"- id: {r.pill}",
            f"  type: {r.type}",
            f"  title: {r.title[:80]}",
            f"  rule: {r.statement[:400]}",
        ]
        if r.rationale:
            lines.append(f"  rationale: {r.rationale[:300]}")
        lines.append(f"  decided: {r.decided_at.date().isoformat() if r.decided_at else 'unknown'}")
        lines.append(f"  scope: {scope[:200]}")
        if r.confidence_band == "low" or r.tentative:
            lines.append("  confidence: tentative (agent-proposed)")
        entries.append("\n".join(lines))
    body = "\n".join(entries).replace("</project_memory>", "")
    return f"<project_memory>\n{body}\n</project_memory>"


class BriefService:
    """Builds the task brief a coding agent receives before it writes code."""

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
    def build_query(task: str, file_paths: list[str] | None = None) -> str:
        query = task.strip()
        if file_paths:
            query += "\nFiles: " + ", ".join(p.strip() for p in file_paths[:10] if p.strip())
        return query

    async def build_brief(
        self,
        db: Session,
        project_id: str,
        task: str,
        file_paths: list[str] | None = None,
        *,
        run_id: str | None = None,
    ) -> BriefResult:
        ctx = BankResolver.resolve(db, project_id)
        try:
            return await self._build(db, ctx, task, file_paths, run_id)
        finally:
            AuditService.flush(db, ctx)

    async def _build(
        self,
        db: Session,
        ctx: ProjectContext,
        task: str,
        file_paths: list[str] | None,
        run_id: str | None,
    ) -> BriefResult:
        query = self.build_query(task, file_paths)
        active = self.memory_service.get_active_records(db, ctx.project_id)
        all_tokens = count_tokens(render_memory_block(active)) if active else 0

        # R3: a project with no memory makes no recall call.
        if not active:
            return BriefResult(
                status="empty",
                message="This project has no active memory yet. Memory forms from reviewed sessions.",
                query=query,
                filter_mode="none",
            )

        if not getattr(self.hindsight, "available", True):
            return BriefResult(
                status="memory_unavailable",
                message="Hindsight is offline, so project memory cannot be recalled right now.",
                query=query,
                filter_mode="none",
                active_records=len(active),
                all_records_tokens=all_tokens,
            )

        try:
            outcome = await self.hindsight.recall_detailed(
                ctx,
                query,
                purpose="brief",
                max_tokens=1500,
                exclude_status=["superseded", "retracted"],
                expect_results=True,
                run_id=run_id,
            )
        except BankMissing:
            project = db.get(Project, ctx.project_id)
            if project:
                project.bank_status = "error"
                project.bank_error = "Hindsight bank not found. Reprovision in Settings."
                db.commit()
            return BriefResult(
                status="memory_unavailable",
                message="The project's Hindsight bank is missing. Reprovision it in Settings.",
                query=query,
                filter_mode="none",
                active_records=len(active),
            )
        except (HindsightUnavailable, AppError) as exc:
            return BriefResult(
                status="memory_unavailable",
                message=f"Recall failed: {getattr(exc, 'message', str(exc))}",
                query=query,
                filter_mode="none",
                active_records=len(active),
            )

        # Group facts by record, keeping the best rank; observations map via source facts.
        active_map = {r.id: r for r in active}
        best_rank: dict[str, int] = {}
        best_score: dict[str, float] = {}
        for fact in outcome.facts:
            for rid in fact.record_ids or [fact.record_id]:
                # PostgreSQL post-filter: retired or retag_pending records never reach the agent.
                if rid in active_map and rid not in best_rank:
                    best_rank[rid] = fact.rank
                    best_score[rid] = fact.score
        observations = [
            Observation(text=o.text, record_ids=[r for r in o.record_ids if r in active_map])
            for o in outcome.observations[:6]
        ]
        recalled = sorted(best_rank, key=lambda rid: best_rank[rid])
        recalled_records = [active_map[rid] for rid in recalled]
        base = {
            "query": outcome.query,
            "recalled": [ref(r) for r in recalled_records],
            "observations": observations,
            "recall_ms": outcome.latency_ms,
            "recall_attempts": outcome.attempts,
            "active_records": len(active),
            "all_records_tokens": all_tokens,
        }
        if not recalled_records:
            return BriefResult(
                status="empty",
                message="No project memory applies to this task.",
                filter_mode="none",
                **base,
            )

        started = time.perf_counter()
        filter_mode = "llm"
        selections: list[ApplicabilityItem] | None
        if not getattr(self.llm, "configured", True):
            # No LLM configured: deterministic scope matching, labelled "heuristic".
            selections = heuristics.applicability(task, recalled_records)
            filter_mode = "heuristic"
        else:
            try:
                selections = await self._llm_applicability(task, recalled_records)
            except AppError:
                selections = None
        filter_ms = int((time.perf_counter() - started) * 1000)

        if selections is None:
            # §16.6: applicability failed → top 3 by rank, labelled "unfiltered".
            filter_mode = "unfiltered"
            chosen = recalled_records[:3]
            applied = [
                AppliedRecord(
                    record=ref(r),
                    rank=i,
                    recall_rank=best_rank[r.id],
                    score=best_score[r.id],
                    reason="Unfiltered: applicability check unavailable; top recall rank.",
                )
                for i, r in enumerate(chosen, start=1)
            ]
            filtered = [
                FilteredRecord(record=ref(r), recall_rank=best_rank[r.id], reason="Below the top-3 recall cut.")
                for r in recalled_records[3:]
            ]
            block = render_memory_block(chosen)
            return BriefResult(
                status="unfiltered",
                message="Applicability filter unavailable; using the top 3 recalled records.",
                applied=applied,
                filtered=filtered,
                filter_mode=filter_mode,
                filter_ms=filter_ms,
                injected_tokens=count_tokens(block),
                memory_block=block,
                **base,
            )

        by_id = {s.record_id: s for s in selections}
        applies = [r for r in recalled_records if by_id.get(r.id) and by_id[r.id].applies]
        applies.sort(key=lambda r: (-(r.importance or 1), best_rank[r.id]))
        chosen = applies[:MAX_APPLIED]
        chosen_ids = {r.id for r in chosen}
        applied = [
            AppliedRecord(
                record=ref(r),
                rank=i,
                recall_rank=best_rank[r.id],
                score=best_score[r.id],
                reason=(by_id[r.id].reason or "Applies to this task.")[:200],
            )
            for i, r in enumerate(chosen, start=1)
        ]
        filtered = []
        for r in recalled_records:
            if r.id in chosen_ids:
                continue
            sel = by_id.get(r.id)
            reason = (sel.reason if sel and not sel.applies else None) or (
                "Applies, but over the 5-record cap." if sel and sel.applies else "Not assessed as applicable."
            )
            filtered.append(FilteredRecord(record=ref(r), recall_rank=best_rank[r.id], reason=reason[:200]))

        block = render_memory_block(chosen)
        for record in chosen:
            record.times_applied = (record.times_applied or 0) + 1
        db.commit()
        return BriefResult(
            status="ok" if chosen else "none_apply",
            message=None if chosen else f"Recalled {len(recalled_records)}, none apply to this task.",
            applied=applied,
            filtered=filtered,
            filter_mode=filter_mode,
            filter_ms=filter_ms,
            injected_tokens=count_tokens(block),
            memory_block=block,
            **base,
        )

    async def _llm_applicability(self, task: str, records: list[MemoryRecord]) -> list[ApplicabilityItem]:
        payload = [
            {
                "record_id": r.id,
                "type": r.type,
                "rule": r.statement[:400],
                "scope": json.loads(r.applies_to_json or "[]") or [r.area or "project-wide"],
            }
            for r in records
        ]
        result = await self.llm.complete_json(
            tier="small",
            messages=[
                {"role": "system", "content": APPLICABILITY_SYSTEM},
                {
                    "role": "user",
                    "content": f"Task:\n{task[:4000]}\n\nRecalled records (data):\n{json.dumps(payload, ensure_ascii=False)}",
                },
            ],
            schema=ApplicabilityResponse,
            job="applicability",
            temperature=0.0,
            max_tokens=1200,
        )
        parsed: ApplicabilityResponse = result.parsed
        return parsed.selections
