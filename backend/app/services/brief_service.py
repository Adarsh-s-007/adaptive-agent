"""Brief Service: Zero-memory short-circuit, recall grouping, applicability filter (BR-1)."""

from __future__ import annotations

import json
import time

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.gateways.hindsight_gateway import HindsightGateway, RecalledFact
from app.gateways.llm_gateway import LLMGateway
from app.gateways.project_context import BankResolver
from app.schemas.common import AppliedRecord, BriefResult, FilteredRecord, RecordRef
from app.services.governed_memory_service import GovernedMemoryService


class ApplicabilityItem(BaseModel):
    record_id: str
    applies: bool = True
    reason: str = Field(..., max_length=150)


class ApplicabilityResponse(BaseModel):
    selections: list[ApplicabilityItem] = Field(default_factory=list)


class BriefService:
    """Orchestrates Brief generation for coding agents before implementing tasks."""

    def __init__(
        self,
        hindsight: HindsightGateway | None = None,
        llm: LLMGateway | None = None,
        memory_service: GovernedMemoryService | None = None,
    ) -> None:
        self.hindsight = hindsight or HindsightGateway()
        self.llm = llm or LLMGateway()
        self.memory_service = memory_service or GovernedMemoryService(self.hindsight)

    async def build_brief(
        self,
        db: Session,
        project_id: str,
        task: str,
        file_paths: list[str] | None = None,
    ) -> BriefResult:
        ctx = BankResolver.resolve(db, project_id)

        # 1. Zero active records short-circuit (R3)
        active_count = self.memory_service.count_active(db, project_id)
        if active_count == 0:
            return BriefResult(
                status="empty",
                query=task,
                recalled=[],
                applied=[],
                filtered=[],
                observations=[],
                recall_ms=0,
                filter_ms=0,
                injected_tokens=0,
            )

        # 2. Query construction
        query = task.strip()
        if file_paths:
            query += f"\nAffected files: {', '.join(file_paths[:10])}"

        # 3. Recall from Hindsight
        recall_start = time.perf_counter()
        recalled_facts: list[RecalledFact] = []
        try:
            recalled_facts = await self.hindsight.recall(
                ctx=ctx,
                query=query,
                purpose="brief",
                max_tokens=1500,
                exclude_status=["superseded", "retracted"],
            )
        except Exception:
            return BriefResult(
                status="memory_unavailable",
                query=query,
                recalled=[],
                applied=[],
                filtered=[],
                observations=[],
                recall_ms=int((time.perf_counter() - recall_start) * 1000),
                filter_ms=0,
                injected_tokens=0,
            )
        recall_ms = int((time.perf_counter() - recall_start) * 1000)

        if not recalled_facts:
            # Fallback to top active records if direct semantic search yielded empty
            active_records = self.memory_service.get_active_records(db, project_id)
            if active_records:
                top_active = active_records[:3]
                applied = [
                    AppliedRecord(
                        record=RecordRef(
                            id=r.id,
                            pill=r.pill,
                            type=r.type,
                            title=r.title,
                            statement=r.statement,
                            area=r.area,
                            importance=r.importance,
                            status=r.status,
                            confidence_band=r.confidence_band,
                            decided_at=r.decided_at.isoformat() if r.decided_at else None,
                        ),
                        rank=idx,
                        reason="Project engineering baseline rule",
                    )
                    for idx, r in enumerate(top_active, start=1)
                ]
                injected = sum(len(r.record.statement.split()) for r in applied)
                return BriefResult(
                    status="unfiltered",
                    query=query,
                    recalled=[a.record for a in applied],
                    applied=applied,
                    filtered=[],
                    observations=[],
                    recall_ms=recall_ms,
                    filter_ms=0,
                    injected_tokens=injected,
                )
            return BriefResult(
                status="empty",
                query=query,
                recalled=[],
                applied=[],
                filtered=[],
                observations=[],
                recall_ms=recall_ms,
                filter_ms=0,
                injected_tokens=0,
            )

        # 4. Status post-filter against DB (exclude any superseded or retracted in Postgres)
        unique_ids = list({f.record_id for f in recalled_facts})
        status_map = self.memory_service.active_status_map(db, project_id, unique_ids)
        valid_facts = [f for f in recalled_facts if status_map.get(f.record_id) == "active"]

        if not valid_facts:
            return BriefResult(
                status="empty",
                query=query,
                recalled=[],
                applied=[],
                filtered=[],
                observations=[],
                recall_ms=recall_ms,
                filter_ms=0,
                injected_tokens=0,
            )

        # Load governed records from DB
        records_db = self.memory_service.get_records(db, [f.record_id for f in valid_facts])
        record_map = {r.id: r for r in records_db}

        recalled_refs = [
            RecordRef(
                id=r.id,
                pill=r.pill,
                type=r.type,
                title=r.title,
                statement=r.statement,
                area=r.area,
                importance=r.importance,
                status=r.status,
                confidence_band=r.confidence_band,
                decided_at=r.decided_at.isoformat() if r.decided_at else None,
                tentative=r.tentative,
            )
            for r in records_db
        ]

        # 5. Applicability filter
        filter_start = time.perf_counter()
        candidates_summary = [
            {"id": r.id, "pill": r.pill, "type": r.type, "title": r.title, "rule": r.statement[:200]}
            for r in records_db
        ]

        prompt_messages = [
            {
                "role": "system",
                "content": (
                    "You are a project memory applicability assessor. Determine if each engineering record "
                    "applies directly to the coding task. Give a crisp reason under 20 words for why it applies or does not apply."
                ),
            },
            {
                "role": "user",
                "content": f"Task: {task}\n\nProject Memory Candidates:\n{json.dumps(candidates_summary, ensure_ascii=False)}",
            },
        ]

        try:
            llm_res = await self.llm.complete_json(
                tier="small",
                messages=prompt_messages,
                schema=ApplicabilityResponse,
                job="applicability",
                temperature=0.0,
            )
            resp: ApplicabilityResponse = llm_res.parsed
            applied_items = [s for s in resp.selections if s.applies and s.record_id in record_map]
            filtered_items = [s for s in resp.selections if not s.applies and s.record_id in record_map]
        except Exception:
            # Fallback to top-3 unfiltered
            applied_items = [
                ApplicabilityItem(record_id=r.id, applies=True, reason="Relevant task pattern")
                for r in records_db[:3]
            ]
            filtered_items = []

        # Sort applied by importance then rank, limit to 5
        applied_sorted = sorted(
            applied_items,
            key=lambda item: record_map[item.record_id].importance,
            reverse=True,
        )[:5]

        applied_refs: list[AppliedRecord] = []
        for idx, item in enumerate(applied_sorted, start=1):
            r = record_map[item.record_id]
            ref = RecordRef(
                id=r.id,
                pill=r.pill,
                type=r.type,
                title=r.title,
                statement=r.statement,
                area=r.area,
                importance=r.importance,
                status=r.status,
                confidence_band=r.confidence_band,
                decided_at=r.decided_at.isoformat() if r.decided_at else None,
                tentative=r.tentative,
            )
            applied_refs.append(AppliedRecord(record=ref, rank=idx, reason=item.reason[:150]))

        filtered_refs: list[FilteredRecord] = []
        for item in filtered_items:
            r = record_map[item.record_id]
            ref = RecordRef(
                id=r.id,
                pill=r.pill,
                type=r.type,
                title=r.title,
                statement=r.statement,
                area=r.area,
                importance=r.importance,
                status=r.status,
                confidence_band=r.confidence_band,
                decided_at=r.decided_at.isoformat() if r.decided_at else None,
            )
            filtered_refs.append(FilteredRecord(record=ref, reason=item.reason[:150]))

        filter_ms = int((time.perf_counter() - filter_start) * 1000)
        injected_tokens = sum(len(a.record.statement.split()) for a in applied_refs)

        return BriefResult(
            status="ok" if applied_refs else "unfiltered",
            query=query,
            recalled=recalled_refs,
            applied=applied_refs,
            filtered=filtered_refs,
            observations=[],
            recall_ms=recall_ms,
            filter_ms=filter_ms,
            injected_tokens=injected_tokens,
        )
