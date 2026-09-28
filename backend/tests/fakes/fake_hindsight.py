"""In-memory HindsightGateway fake: banks, documents, tags, recall, reflect, mental models.

Recall ranks documents by keyword overlap so tests are deterministic. It records every
call so tests can assert, for example, that a baseline run makes zero Hindsight calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.gateways.hindsight_gateway import (
    BankMissing,
    HindsightUnavailable,
    RecalledFact,
    RecallOutcome,
    project_tag_groups,
)
from app.gateways.project_context import ProjectContext


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_]+", (text or "").lower()) if len(w) > 2}


@dataclass
class StoredDoc:
    document_id: str
    record_id: str
    project_id: str
    content: str
    tags: list[str]
    metadata: dict[str, str]
    retain_count: int = 1


@dataclass
class FakeHindsight:
    banks: dict[str, dict[str, StoredDoc]] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    offline: bool = False
    fail_retain: bool = False
    fail_retag: bool = False
    fail_recall: bool = False
    foreign_injection: dict[str, Any] | None = None
    rulebook: dict[str, str] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=lambda: {"empty_recall_retries": 0})
    _isolation: int = 0

    # ------------------------------------------------------------------ state
    @property
    def configured(self) -> bool:
        return True

    @property
    def available(self) -> bool:
        return not self.offline

    @property
    def is_forced_offline(self) -> bool:
        return self.offline

    def set_force_offline(self, value: bool) -> None:
        self.offline = value

    @property
    def isolation_violations_blocked(self) -> int:
        return self._isolation

    def _check(self, op: str, ctx: ProjectContext) -> dict[str, StoredDoc]:
        self.calls.append((op, ctx.bank_id))
        if self.offline:
            raise HindsightUnavailable("Hindsight is forced offline.")
        if ctx.bank_id not in self.banks:
            raise BankMissing(f"bank {ctx.bank_id} not found", status=404)
        return self.banks[ctx.bank_id]

    async def health(self) -> dict[str, Any]:
        return {"status": "offline" if self.offline else "ok", "latency_ms": 1}

    async def aclose(self) -> None:
        return None

    # ------------------------------------------------------------ provisioning
    async def provision_bank(self, ctx: ProjectContext, project_name: str | None = None, description: str = ""):
        self.calls.append(("provision", ctx.bank_id))
        if self.offline:
            raise HindsightUnavailable("offline")
        self.banks.setdefault(ctx.bank_id, {})
        ctx.audit("PROVISION", detail={"bank_id": ctx.bank_id})
        return {"status": "ready", "bank_id": ctx.bank_id, "mental_model_id": "rulebook", "directives_created": 3}

    async def ensure_rulebook(self, ctx: ProjectContext) -> str:
        return "rulebook"

    async def delete_bank(self, ctx: ProjectContext) -> None:
        self.calls.append(("delete_bank", ctx.bank_id))
        self.banks.pop(ctx.bank_id, None)

    async def list_directives(self, ctx):
        return [{"name": "memory-only", "content": "Answer only from memory."}]

    async def get_bank_config(self, ctx):
        return {"retain_extraction_mode": "verbatim"}

    async def bank_stats(self, ctx):
        return {"documents": len(self.banks.get(ctx.bank_id, {}))}

    # ------------------------------------------------------------------ retain
    async def retain_record(self, ctx: ProjectContext, record_id: str, content: str, memory_type: str, *args, **kwargs):
        docs = self._check("retain", ctx)
        if kwargs.get("project_id") is not None:
            ctx.assert_writable(kwargs["project_id"], ctx.bank_id)
        if self.fail_retain:
            raise HindsightUnavailable("Simulated retain failure")
        tags = kwargs.get("record_tags") or [f"project:{ctx.project_id}", f"type:{memory_type}", "status:active"]
        doc_id = f"mem_{record_id}"
        existing = docs.get(doc_id)
        docs[doc_id] = StoredDoc(
            document_id=doc_id,
            record_id=record_id,
            project_id=ctx.project_id,
            content=content,
            tags=list(tags),
            metadata={"record_id": record_id, "project_id": ctx.project_id},
            retain_count=(existing.retain_count + 1) if existing else 1,
        )
        ctx.audit("RETAIN", record_id=record_id, latency_ms=1)
        return {"document_id": doc_id, "success": True}

    async def update_document_tags(self, ctx: ProjectContext, record_id: str, new_tags: list[str]) -> bool:
        try:
            docs = self._check("retag", ctx)
        except HindsightUnavailable:
            return False
        if self.fail_retag:
            return False
        doc = docs.get(f"mem_{record_id}")
        if not doc:
            return False
        doc.tags = list(new_tags)
        ctx.audit("RETAG", record_id=record_id)
        return True

    async def retag_document(self, ctx, record_id, new_tags):
        return await self.update_document_tags(ctx, record_id, new_tags)

    async def get_document(self, ctx: ProjectContext, record_id: str):
        docs = self._check("get_document", ctx)
        doc = docs.get(f"mem_{record_id}")
        if not doc:
            return None
        return {"id": doc.document_id, "tags": doc.tags, "document_metadata": doc.metadata, "memory_unit_count": 1}

    # ------------------------------------------------------------------ recall
    async def recall_detailed(self, ctx: ProjectContext, query: str, *, purpose="brief", max_tokens=1500,
                              budget="mid", exclude_status=None, expect_results=False, run_id=None) -> RecallOutcome:
        docs = self._check(f"recall:{purpose}", ctx)
        if self.fail_recall:
            raise HindsightUnavailable("Simulated recall timeout")
        exclude = exclude_status if exclude_status is not None else ["superseded", "retracted"]
        q = _words(query)
        items = list(docs.values())
        if self.foreign_injection:
            items.append(StoredDoc(**self.foreign_injection))
        scored = []
        for doc in items:
            overlap = len(q & _words(doc.content))
            if overlap:
                scored.append((overlap, doc))
        scored.sort(key=lambda x: -x[0])
        facts = []
        dropped = 0
        for rank, (score, doc) in enumerate(scored[:10], start=1):
            if not ctx.assert_record_isolated(doc.project_id):
                self._isolation += 1
                dropped += 1
                continue
            if any(f"status:{s}" in doc.tags for s in exclude):
                continue
            facts.append(
                RecalledFact(
                    record_id=doc.record_id, text=doc.content, fact_type="world", rank=rank, score=float(score),
                    metadata=doc.metadata, tags=doc.tags, document_id=doc.document_id, record_ids=[doc.record_id],
                )
            )
        ctx.audit("RECALL", latency_ms=1, detail={"purpose": purpose, "query": query[:100]})
        return RecallOutcome(query=query, facts=facts, observations=[], latency_ms=1, attempts=1, dropped_foreign=dropped)

    async def recall(self, ctx, query, purpose="brief", max_tokens=1500, exclude_status=None, expect_results=False):
        return (await self.recall_detailed(ctx, query, purpose=purpose, exclude_status=exclude_status)).facts

    # ----------------------------------------------------------------- reflect
    async def reflect(self, ctx: ProjectContext, query: str, max_tokens=1200, budget="mid", exclude_status=None):
        outcome = await self.recall_detailed(ctx, query, purpose="reflect", exclude_status=[])
        memories = [{"id": f"unit-{f.record_id}", "text": f.text, "type": "world"} for f in outcome.facts[:3]]
        return {
            "answer": f"Based on project memory: {outcome.facts[0].text[:120]}" if outcome.facts else "No memory applies.",
            "memories": memories,
            "directives": [{"name": "memory-only", "content": "Answer only from memory."}],
            "mental_models": [],
            "usage": {},
            "latency_ms": 1,
            "based_on": [m["id"] for m in memories],
        }

    async def resolve_units(self, ctx, unit_ids):
        return {u: [u.replace("unit-", "")] for u in unit_ids}

    async def get_mental_model(self, ctx, model_id="rulebook", detail="content"):
        self._check("get_mental_model", ctx)
        return {"id": "rulebook", "content": self.rulebook.get(ctx.bank_id, "## Rules\n- none yet"), "last_refreshed_at": None}

    async def refresh_mental_model(self, ctx, model_id="rulebook"):
        docs = self._check("refresh_mental_model", ctx)
        active = [d for d in docs.values() if "status:active" in d.tags]
        self.rulebook[ctx.bank_id] = "## Rules\n" + "\n".join(f"- {d.content.splitlines()[0]}" for d in active)
        return "op-1"

    async def mental_model_history(self, ctx, model_id="rulebook"):
        return []

    def docs(self, bank_id: str) -> dict[str, StoredDoc]:
        return self.banks.get(bank_id, {})

    def recall_calls(self) -> int:
        return sum(1 for op, _ in self.calls if op.startswith("recall"))

    def reset_calls(self) -> None:
        self.calls.clear()


__all__ = ["FakeHindsight", "project_tag_groups"]
