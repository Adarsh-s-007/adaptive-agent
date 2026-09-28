"""Project scoped Hindsight Cloud integration."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from app.config import get_settings


class HindsightService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _headers(self) -> dict[str, str]:
        if not self.settings.hindsight_api_key:
            raise HTTPException(
                503, "Hindsight is not configured. Add HINDSIGHT_API_KEY to .env."
            )
        return {
            "Authorization": f"Bearer {self.settings.hindsight_api_key}",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.settings.hindsight_base_url.rstrip('/')}/v1/default{path}"

    async def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.request(
                    method, self._url(path), headers=self._headers(), json=payload
                )
                response.raise_for_status()
                return response.json() if response.content else {}
        except HTTPException:
            raise
        except httpx.HTTPStatusError as exc:
            # Provider responses may contain sensitive request details.
            raise HTTPException(
                502,
                f"Hindsight rejected the request (HTTP {exc.response.status_code}). "
                "Check the bank and Hindsight account.",
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, "Hindsight is temporarily unreachable.") from exc

    @staticmethod
    def bank_slug(name: str, project_id: str) -> str:
        safe = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:42] or "project"
        return f"projectpulse-{safe}-{project_id[:8]}"

    async def create_bank(
        self, bank_id: str, name: str, description: str
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            f"/banks/{quote(bank_id, safe='')}",
            {
                "name": name,
                "retain_mission": (
                    "Extract durable engineering decisions, API contracts, bug causes, "
                    "fixes and failed approaches. Preserve explicit do-not-use constraints."
                ),
                "reflect_mission": f"Reason only about the {name} software project. {description}".strip(),
            },
        )

    async def retain(
        self,
        bank_id: str,
        *,
        content: str,
        document_id: str,
        metadata: dict[str, str],
        tags: list[str],
    ) -> dict[str, Any]:
        return await self.retain_batch(
            bank_id,
            [
                {
                    "content": content,
                    "document_id": document_id,
                    "metadata": metadata,
                    "tags": tags,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
        )

    async def retain_batch(
        self, bank_id: str, items: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/banks/{quote(bank_id, safe='')}/memories",
            {"items": items, "async": False},
        )

    async def recall(
        self, bank_id: str, project_id: str, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        # Hindsight's current HTTP schema uses max_tokens and nested include options.
        data = await self._request(
            "POST",
            f"/banks/{quote(bank_id, safe='')}/memories/recall",
            {
                "query": query,
                "budget": "mid",
                "max_tokens": 1800,
                "tags": [f"project:{project_id}"],
                "tags_match": "any_strict",
                "include": {"entities": None, "chunks": {"max_tokens": 1600}},
            },
        )
        raw = data.get("results", [])
        if not isinstance(raw, list):
            raise HTTPException(
                502, "Hindsight returned an unexpected Recall response."
            )
        chunks = data.get("chunks") or {}
        return [self._normalise(item, chunks) for item in raw[:limit]]

    @staticmethod
    def _normalise(item: Any, chunks: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(item, dict) or not item.get("id") or not item.get("text"):
            raise HTTPException(502, "Hindsight returned an unexpected memory item.")
        chunk = chunks.get(item.get("chunk_id")) or {}
        scores = item.get("scores") or {}
        return {
            "id": item["id"],
            "text": item["text"],
            "type": item.get("type") or "memory",
            "metadata": item.get("metadata") or {},
            "document_id": item.get("document_id"),
            "timestamp": item.get("mentioned_at") or item.get("occurred_start"),
            "source_text": chunk.get("text") if isinstance(chunk, dict) else None,
            "relevance": scores.get("final"),
            "why_relevant": None,
        }
