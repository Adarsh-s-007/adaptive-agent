"""Minimal in-memory Hindsight stand-in for P3/P5 unit tests. Owner: P3.

P2's tests/fakes/fake_hindsight.py is the reference fake; switch to it once it lands.
"""

from __future__ import annotations

import re
import uuid

from app.core.errors import AppError, ErrorCode
from app.db.models import Project
from app.gateways.hindsight_gateway import RecalledFact, RetainDocument


class MiniHindsight:
    def __init__(self) -> None:
        self.docs: dict[str, RetainDocument] = {}
        self.fail = False
        self.recall_calls = 0

    def _check(self) -> None:
        if self.fail:
            raise AppError(ErrorCode.HINDSIGHT_UNAVAILABLE, "Hindsight is offline (fake).")

    async def retain_record(self, ctx, doc: RetainDocument, *, async_: bool = False) -> None:
        self._check()
        assert doc.metadata["project_id"] == str(ctx.project_id)
        self.docs[doc.record_id] = doc

    async def retag(self, ctx, record_id: str, tags: list[str]) -> None:
        self._check()
        self.docs[record_id].tags = tags

    async def recall(self, ctx, query: str, *, purpose: str, max_tokens: int = 1500):
        self._check()
        self.recall_calls += 1
        words = set(re.findall(r"[a-z]{4,}", query.lower()))
        hits = []
        for doc in self.docs.values():
            if doc.metadata["project_id"] != str(ctx.project_id):
                continue
            if any(t in doc.tags for t in ("status:superseded", "status:retracted")):
                continue
            score = len(words & set(re.findall(r"[a-z]{4,}", doc.content.lower())))
            if score:
                hits.append((score, doc))
        hits.sort(key=lambda h: -h[0])
        return [
            RecalledFact(
                record_id=d.record_id, text=d.content, fact_type="world", rank=i + 1, score=s
            )
            for i, (s, d) in enumerate(hits)
        ]


async def make_project(db, name: str = "ApexCart") -> Project:
    pid = uuid.uuid4()
    project = Project(
        id=pid,
        slug=f"{name.lower()}-{pid.hex[:6]}",
        name=name,
        description="Next.js storefront",
        tech_stack=["Next.js", "Prisma"],
        areas=["auth", "database"],
        hindsight_bank_id=f"pp_{name.lower()}_{pid.hex[:8]}",
        bank_status="ready",
    )
    db.add(project)
    await db.commit()
    return project
