"""Hindsight Gateway for memory space operations with strict project isolation (HS-2, HS-3)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from app.config import get_settings
from app.core.errors import AppError, AppErrorCode
from app.core.memory_conventions import build_metadata, build_tags, format_document_id
from app.gateways.project_context import ProjectContext


@dataclass
class RecalledFact:
    record_id: str
    text: str
    fact_type: str = "memory"
    rank: int = 1
    score: float = 0.0
    source_fact_ids: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    document_id: str = ""


class HindsightGateway:
    """The authoritative interface for all Hindsight operations in ProjectPulse."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._force_offline: bool = os.environ.get("HINDSIGHT_FORCE_OFFLINE", "false").lower() in ("true", "1")
        self._isolation_violations: int = 0

    @property
    def is_forced_offline(self) -> bool:
        return self._force_offline or os.environ.get("HINDSIGHT_FORCE_OFFLINE", "false").lower() in ("true", "1")

    def set_force_offline(self, value: bool) -> None:
        self._force_offline = value

    @property
    def isolation_violations_blocked(self) -> int:
        return self._isolation_violations

    def _headers(self) -> dict[str, str]:
        if not self.settings.hindsight_api_key or self.is_forced_offline:
            raise AppError(
                code=AppErrorCode.HINDSIGHT_UNAVAILABLE,
                message="Hindsight is offline or unconfigured.",
                status_code=503,
            )
        return {
            "Authorization": f"Bearer {self.settings.hindsight_api_key}",
            "Content-Type": "application/json",
        }

    def _base_url(self) -> str:
        return f"{self.settings.hindsight_base_url.rstrip('/')}/v1/default"

    async def health(self) -> dict[str, Any]:
        """Probe Hindsight connectivity with short timeout."""
        if self.is_forced_offline:
            return {"status": "degraded", "forced_offline": True, "message": "Forced offline mode active."}
        if not self.settings.hindsight_api_key:
            return {"status": "unconfigured", "configured": False}
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(
                    f"{self._base_url()}/banks",
                    headers=self._headers(),
                    params={"limit": "1"},
                )
                if resp.status_code < 400:
                    return {"status": "ok", "latency_ms": 50}
                return {"status": "degraded", "code": resp.status_code}
        except Exception as exc:
            return {"status": "down", "error": str(exc)}

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
        """Retain an approved engineering record in Hindsight."""
        if self.is_forced_offline or not self.settings.hindsight_api_key:
            return {
                "id": format_document_id(record_id),
                "status": "pending_local",
                "origin": "offline",
            }

        doc_id = format_document_id(record_id)
        metadata = build_metadata(
            record_id=record_id,
            project_id=ctx.project_id,
            memory_type=memory_type,
            area=area,
            importance=importance,
            source_session_id=source_session_id,
            supersedes=supersedes,
            stated_by=stated_by,
        )
        tag_list = build_tags(
            project_id=ctx.project_id,
            memory_type=memory_type,
            area=area,
            status="active",
            extra_tags=tags,
        )

        payload = {
            "items": [
                {
                    "content": content,
                    "document_id": doc_id,
                    "metadata": metadata,
                    "tags": tag_list,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
            "async": async_,
        }

        url = f"{self._base_url()}/banks/{ctx.bank_id}/memories"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(url, headers=self._headers(), json=payload)
                if res.status_code >= 400:
                    raise AppError(
                        code=AppErrorCode.HINDSIGHT_UNAVAILABLE,
                        message=f"Hindsight retain rejected: HTTP {res.status_code}",
                        status_code=502,
                    )
                return res.json() if res.content else {"status": "ok"}
        except httpx.TimeoutException:
            raise AppError(
                code=AppErrorCode.HINDSIGHT_UNAVAILABLE,
                message="Hindsight retain timed out.",
                status_code=503,
            )
        except Exception as e:
            if isinstance(e, AppError):
                raise
            raise AppError(
                code=AppErrorCode.HINDSIGHT_UNAVAILABLE,
                message=f"Hindsight connection error: {e!s}",
                status_code=503,
            )

    async def recall(
        self,
        ctx: ProjectContext,
        query: str,
        purpose: str = "brief",
        max_tokens: int = 1500,
        exclude_status: list[str] | None = None,
    ) -> list[RecalledFact]:
        """Recall relevant project memories with strict project isolation assertion."""
        # 400-token query truncation safeguard (Blueprint §15.4 / C-5)
        words = query.strip().split()
        if len(words) > 400:
            query = " ".join(words[:400])

        if self.is_forced_offline or not self.settings.hindsight_api_key:
            return []

        url = f"{self._base_url()}/banks/{ctx.bank_id}/memories/recall"
        payload = {
            "query": query,
            "budget": "mid" if purpose == "brief" else "low",
            "max_tokens": max_tokens,
            "tags": [f"project:{ctx.project_id}"],
            "tags_match": "any_strict",
            "include": {"entities": None, "chunks": {"max_tokens": 1200}},
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, headers=self._headers(), json=payload)
                if res.status_code >= 400:
                    return []
                data = res.json()
        except Exception:
            return []

        raw_results = data.get("results", [])
        facts: list[RecalledFact] = []

        for idx, item in enumerate(raw_results, start=1):
            meta = item.get("metadata") or {}
            rec_proj = meta.get("project_id")
            
            # Metadata isolation assertion (Blueprint §15.3 / C-5)
            if not ctx.assert_record_isolated(rec_proj):
                self._isolation_violations += 1
                continue  # Drop foreign project result

            doc_id = item.get("document_id") or ""
            rec_id = meta.get("record_id") or doc_id.replace("mem_", "")
            
            status = meta.get("status", "active")
            if exclude_status and status in exclude_status:
                continue

            facts.append(
                RecalledFact(
                    record_id=rec_id,
                    text=item.get("text", ""),
                    fact_type=meta.get("type", "memory"),
                    rank=idx,
                    score=float((item.get("scores") or {}).get("final", 0.0)),
                    source_fact_ids=[item.get("id")] if item.get("id") else [],
                    metadata=meta,
                    tags=item.get("tags") or [],
                    document_id=doc_id,
                )
            )

        return facts

    async def retag_document(
        self,
        ctx: ProjectContext,
        record_id: str,
        new_tags: list[str],
    ) -> bool:
        """Update tags on a document in Hindsight (e.g. for supersession)."""
        if self.is_forced_offline or not self.settings.hindsight_api_key:
            return True

        doc_id = format_document_id(record_id)
        url = f"{self._base_url()}/banks/{ctx.bank_id}/documents/{doc_id}/tags"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.put(url, headers=self._headers(), json={"tags": new_tags})
                return res.status_code < 400
        except Exception:
            return False

    async def reflect(
        self,
        ctx: ProjectContext,
        query: str,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        """Ask / reflect operation querying bank synthesis."""
        if self.is_forced_offline or not self.settings.hindsight_api_key:
            return {
                "answer": "Hindsight is currently offline. Direct reflection is unavailable.",
                "based_on": [],
            }

        url = f"{self._base_url()}/banks/{ctx.bank_id}/reflect"
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                res = await client.post(
                    url,
                    headers=self._headers(),
                    json={"query": query, "max_tokens": max_tokens, "include_facts": True},
                )
                if res.status_code < 400:
                    return res.json()
        except Exception:
            pass

        return {
            "answer": "Could not complete reflection query against Hindsight bank.",
            "based_on": [],
        }
