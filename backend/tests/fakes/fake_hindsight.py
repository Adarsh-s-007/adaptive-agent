"""In-memory test fake for HindsightGateway supporting tags, isolation and retagging (HS-5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.gateways.hindsight_gateway import RecalledFact
from app.gateways.project_context import ProjectContext


@dataclass
class StoredDoc:
    document_id: str
    record_id: str
    project_id: str
    content: str
    memory_type: str
    tags: list[str]
    metadata: dict[str, str]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class FakeHindsight:
    """Deterministic in-memory Hindsight mock for tests and offline development."""

    def __init__(self) -> None:
        self.banks: dict[str, dict[str, Any]] = {}
        self.documents: dict[str, list[StoredDoc]] = {}  # bank_id -> docs
        self.isolation_blocked_count: int = 0
        self.simulated_error: str | None = None

    def set_error(self, error: str | None) -> None:
        self.simulated_error = error

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "mock": True}

    async def retain_record(
        self,
        ctx: ProjectContext,
        record_id: str,
        content: str,
        memory_type: str,
        area: str | None = None,
        importance: int = 3,
        source_session_id: str | None = None,
        supersedes: str | None = None,
        stated_by: str | None = None,
        tags: list[str] | None = None,
        async_: bool = False,
    ) -> dict[str, Any]:
        if self.simulated_error:
            raise Exception(self.simulated_error)

        doc_id = f"mem_{record_id}"
        doc = StoredDoc(
            document_id=doc_id,
            record_id=record_id,
            project_id=ctx.project_id,
            content=content,
            memory_type=memory_type,
            tags=tags or [f"project:{ctx.project_id}", f"type:{memory_type}", "status:active"],
            metadata={
                "record_id": record_id,
                "project_id": ctx.project_id,
                "type": memory_type,
                "area": area or "",
                "importance": str(importance),
                "source_session_id": source_session_id or "",
                "supersedes": supersedes or "",
                "stated_by": stated_by or "",
            },
        )
        if ctx.bank_id not in self.documents:
            self.documents[ctx.bank_id] = []
        
        # Replace if exists
        self.documents[ctx.bank_id] = [d for d in self.documents[ctx.bank_id] if d.document_id != doc_id]
        self.documents[ctx.bank_id].append(doc)

        return {"id": doc_id, "status": "stored", "bank_id": ctx.bank_id}

    async def recall(
        self,
        ctx: ProjectContext,
        query: str,
        purpose: str = "brief",
        max_tokens: int = 1500,
        exclude_status: list[str] | None = None,
    ) -> list[RecalledFact]:
        if self.simulated_error:
            return []

        docs = self.documents.get(ctx.bank_id, [])
        query_words = set(query.lower().split())
        matched: list[tuple[float, StoredDoc]] = []

        for doc in docs:
            # Isolation check
            if not ctx.assert_record_isolated(doc.project_id):
                self.isolation_blocked_count += 1
                continue

            status = "active"
            for t in doc.tags:
                if t.startswith("status:"):
                    status = t.split(":", 1)[1]
            if exclude_status and status in exclude_status:
                continue

            content_words = set(doc.content.lower().split())
            overlap = len(query_words & content_words)
            score = 0.5 + (0.1 * min(overlap, 5))
            matched.append((score, doc))

        matched.sort(key=lambda p: p[0], reverse=True)

        facts: list[RecalledFact] = []
        for idx, (score, doc) in enumerate(matched, start=1):
            facts.append(
                RecalledFact(
                    record_id=doc.record_id,
                    text=doc.content,
                    fact_type=doc.memory_type,
                    rank=idx,
                    score=score,
                    source_fact_ids=[doc.document_id],
                    metadata=doc.metadata,
                    tags=doc.tags,
                    document_id=doc.document_id,
                )
            )
        return facts

    async def retag_document(
        self,
        ctx: ProjectContext,
        record_id: str,
        new_tags: list[str],
    ) -> bool:
        doc_id = f"mem_{record_id}"
        docs = self.documents.get(ctx.bank_id, [])
        for doc in docs:
            if doc.document_id == doc_id:
                doc.tags = new_tags
                return True
        return False

    async def reflect(
        self,
        ctx: ProjectContext,
        query: str,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        docs = self.documents.get(ctx.bank_id, [])
        recs = [d.record_id for d in docs[:3]]
        return {
            "answer": f"Reflection synthesis based on {len(recs)} active decisions in {ctx.project_name}.",
            "based_on": recs,
        }
