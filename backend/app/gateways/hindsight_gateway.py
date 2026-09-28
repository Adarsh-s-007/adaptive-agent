"""The only module that talks to Hindsight (contract C-5). Owner: P2.

Stub with the frozen signatures so P3/P5/P6 can code against it. P2 replaces bodies.
Every method takes a resolved ProjectContext, never a raw bank id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from app.core.config import get_settings
from app.core.errors import not_implemented
from app.gateways.project_context import ProjectContext


@dataclass
class RetainDocument:
    record_id: str
    content: str
    timestamp: str  # ISO decided_at
    tags: list[str]
    metadata: dict[str, str]
    context: str
    entities: list[str] = field(default_factory=list)


@dataclass
class RecalledFact:
    record_id: str
    text: str
    fact_type: str
    rank: int
    score: float | None = None
    source_fact_ids: list[str] = field(default_factory=list)


@dataclass
class ReflectResult:
    answer: str
    based_on_record_ids: list[str]
    directives: list[str]


class HindsightGateway:
    async def provision(self, ctx: ProjectContext, profile: dict) -> str:
        """Create bank, config, directives, Rulebook mental model. Returns mental model id."""
        raise not_implemented("P2")

    async def retain_record(
        self, ctx: ProjectContext, doc: RetainDocument, *, async_: bool = False
    ) -> None:
        raise not_implemented("P2")

    async def recall(
        self, ctx: ProjectContext, query: str, *, purpose: str, max_tokens: int = 1500
    ) -> list[RecalledFact]:
        """purpose: brief | check | relate. Excludes retired statuses; asserts project_id."""
        raise not_implemented("P2")

    async def reflect(self, ctx: ProjectContext, question: str) -> ReflectResult:
        raise not_implemented("P2")

    async def rulebook_get(self, ctx: ProjectContext) -> str:
        raise not_implemented("P2")

    async def rulebook_refresh(self, ctx: ProjectContext) -> str:
        raise not_implemented("P2")

    async def rulebook_history(self, ctx: ProjectContext) -> list[dict]:
        raise not_implemented("P2")

    async def retag(self, ctx: ProjectContext, record_id: str, tags: list[str]) -> None:
        raise not_implemented("P2")

    async def document_exists(self, ctx: ProjectContext, record_id: str) -> bool:
        raise not_implemented("P2")

    async def health(self) -> str:
        if get_settings().hindsight_force_offline:
            return "down"
        return "ok" if get_settings().hindsight_api_key else "down"


@lru_cache
def get_hindsight_gateway() -> HindsightGateway:
    return HindsightGateway()
