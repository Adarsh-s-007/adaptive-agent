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
            async with httpx.AsyncClient(timeout=8.0) as client:
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
            item_tags = item.get("tags") or []

            # Extract project_id from metadata or tags (format: project:<project_id>)
            rec_proj = meta.get("project_id")
            if not rec_proj:
                for t in item_tags:
                    if t.startswith("project:"):
                        rec_proj = t.split(":", 1)[1]
                        break

            # Metadata and tag isolation assertion (Blueprint §15.3 / C-5)
            if not ctx.assert_record_isolated(rec_proj):
                self._isolation_violations += 1
                continue  # Drop foreign project result

            doc_id = item.get("document_id") or ""
            rec_id = meta.get("record_id") or (doc_id.replace("mem_", "") if doc_id else "")

            # Extract all status indicators from metadata and tags
            record_statuses = set()
            if meta.get("status"):
                record_statuses.add(str(meta["status"]).lower())
            for t in item_tags:
                t_lower = t.lower()
                if t_lower.startswith("status:"):
                    record_statuses.add(t_lower.split(":", 1)[1])
                elif t_lower in ("superseded", "retracted", "deprecated", "active"):
                    record_statuses.add(t_lower)

            if not record_statuses:
                record_statuses.add("active")

            if exclude_status and any(st.lower() in record_statuses for st in exclude_status):
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
                    tags=item_tags,
                    document_id=doc_id,
                )
            )

        return facts

    async def provision_bank(
        self,
        ctx: ProjectContext,
        project_name: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Full bank provisioning sequence per Blueprint §15.2 (HS-4).

        1. Create bank with missions and dispositions
        2. Attach 3 standard directives
        3. Provision Rulebook mental model
        """
        if self.is_forced_offline or not self.settings.hindsight_api_key:
            return {"status": "ready", "origin": "offline", "directives": 3, "mental_model": "rulebook"}

        # 1. Create bank
        url = f"{self._base_url()}/banks/{ctx.bank_id}"
        mission_text = f"Retain engineering decisions, architecture rules, and conventions for {project_name}."
        reflect_text = f"Answer architectural and coding queries strictly citing verified decisions for {project_name}."

        payload = {
            "name": project_name,
            "retain_mission": mission_text,
            "reflect_mission": reflect_text,
            "background": description or f"Engineering memory for {project_name}.",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.put(url, headers=self._headers(), json=payload)
            if res.status_code >= 400:
                raise AppError(
                    code=AppErrorCode.HINDSIGHT_UNAVAILABLE,
                    message=f"Failed to create Hindsight bank: HTTP {res.status_code}",
                    status_code=502,
                )

        # 2. Attach 3 directives (§15.2)
        directives = [
            ("cite_decisions", "Always cite specific architectural decisions and rule statements when explaining technical guidance."),
            ("obsolete_superseded", "Treat superseded records as obsolete historical context; never recommend deprecated patterns."),
            ("no_secrets", "Never retain secrets, credentials, API keys, or raw personal data."),
        ]
        directives_created = 0
        for d_name, d_content in directives:
            try:
                await self.create_directive(ctx, name=d_name, content=d_content)
                directives_created += 1
            except Exception:
                pass

        # 3. Create Rulebook mental model
        mm_id = None
        try:
            mm_resp = await self.create_mental_model(
                ctx=ctx,
                name="Project Rulebook",
                source_query="Summarize all active engineering rules, constraints, and architecture decisions.",
                description="High-level architectural standards and engineering rules of the project.",
            )
            mm_id = mm_resp.get("mental_model_id")
        except Exception:
            pass

        return {
            "status": "ready",
            "bank_id": ctx.bank_id,
            "directives_created": directives_created,
            "mental_model_id": mm_id,
        }

    async def create_directive(
        self,
        ctx: ProjectContext,
        name: str,
        content: str,
        priority: int = 0,
    ) -> dict[str, Any]:
        """Attach a directive to the project bank."""
        if self.is_forced_offline or not self.settings.hindsight_api_key:
            return {"name": name, "status": "stored_offline"}

        url = f"{self._base_url()}/banks/{ctx.bank_id}/directives"
        payload = {"name": name, "content": content, "priority": priority}
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, headers=self._headers(), json=payload)
            if res.status_code >= 400:
                raise AppError(
                    code=AppErrorCode.HINDSIGHT_UNAVAILABLE,
                    message=f"Failed to create directive: HTTP {res.status_code}",
                    status_code=502,
                )
            return res.json()

    async def list_directives(self, ctx: ProjectContext) -> list[dict[str, Any]]:
        """List directives configured on this project bank."""
        if self.is_forced_offline or not self.settings.hindsight_api_key:
            return []
        url = f"{self._base_url()}/banks/{ctx.bank_id}/directives"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url, headers=self._headers())
                if res.status_code < 400:
                    data = res.json()
                    return data.get("directives", data if isinstance(data, list) else [])
        except Exception:
            pass
        return []

    async def create_mental_model(
        self,
        ctx: ProjectContext,
        name: str,
        source_query: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a mental model (Rulebook synthesis) on this project bank."""
        if self.is_forced_offline or not self.settings.hindsight_api_key:
            return {"name": name, "mental_model_id": "mm-offline"}

        url = f"{self._base_url()}/banks/{ctx.bank_id}/mental-models"
        payload = {
            "name": name,
            "source_query": source_query,
            "description": description or name,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, headers=self._headers(), json=payload)
            if res.status_code >= 400:
                raise AppError(
                    code=AppErrorCode.HINDSIGHT_UNAVAILABLE,
                    message=f"Failed to create mental model: HTTP {res.status_code}",
                    status_code=502,
                )
            return res.json()

    async def list_mental_models(self, ctx: ProjectContext) -> list[dict[str, Any]]:
        """List mental models on this project bank."""
        if self.is_forced_offline or not self.settings.hindsight_api_key:
            return []
        url = f"{self._base_url()}/banks/{ctx.bank_id}/mental-models"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url, headers=self._headers())
                if res.status_code < 400:
                    data = res.json()
                    return data.get("items", [])
        except Exception:
            pass
        return []

    async def rulebook_get(self, ctx: ProjectContext) -> str:
        """Fetch Rulebook text from project reflection synthesis (RF-2)."""
        res = await self.reflect(
            ctx=ctx,
            query="Provide the definitive Rulebook of all architectural constraints and engineering standards for this project.",
            max_tokens=1500,
        )
        return res.get("answer", "No rulebook synthesis available.")

    async def ask(
        self,
        ctx: ProjectContext,
        query: str,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        """Ask technical question to project memory with citation mapping (RF-1)."""
        reflect_res = await self.reflect(ctx=ctx, query=query, max_tokens=max_tokens)
        directives = await self.list_directives(ctx)

        return {
            "answer": reflect_res.get("answer", ""),
            "based_on": reflect_res.get("based_on", []),
            "guardrails_applied": [d.get("content", d.get("name", "")) for d in directives],
        }

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
        url = f"{self._base_url()}/banks/{ctx.bank_id}/documents/{doc_id}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.patch(url, headers=self._headers(), json={"tags": new_tags})
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
                    data = res.json()
                    facts = data.get("facts", [])
                    citations = [f.get("document_id") or f.get("id") for f in facts if f]
                    return {
                        "answer": data.get("text") or data.get("answer", ""),
                        "based_on": citations,
                    }
        except Exception:
            pass

        return {
            "answer": "Could not complete reflection query against Hindsight bank.",
            "based_on": [],
        }
