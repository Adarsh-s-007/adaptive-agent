"""Reflect: the Project Rulebook mental model, its history, Ask-the-Project and export (§4.3, §15.5-15.6)."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, AppErrorCode
from app.core.taxonomy import MEMORY_TYPES, normalize_type
from app.db.governed_models import MemoryRecord, RulebookSnapshot
from app.gateways.hindsight_gateway import (
    RULEBOOK_MODEL_ID,
    HindsightGateway,
    HindsightUnavailable,
)
from app.gateways.project_context import context_for, get_project
from app.services.audit_service import AuditService
from app.services.governed_memory_service import GovernedMemoryService
from app.services.serializers import iso, record_ref

PENDING_MARKERS = ("Generating content", "")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReflectService:
    def __init__(self, gateway: HindsightGateway | None = None, memory_service: GovernedMemoryService | None = None):
        from app.gateways.hindsight_gateway import get_hindsight_gateway

        self.gateway = gateway or get_hindsight_gateway()
        self.memory_service = memory_service or GovernedMemoryService(self.gateway)

    # --------------------------------------------------------------- rulebook
    def _snapshot(self, db: Session, project, content: str, source: str, trigger: str | None) -> None:
        last = db.scalar(
            select(RulebookSnapshot)
            .where(RulebookSnapshot.project_id == project.id)
            .order_by(RulebookSnapshot.refreshed_at.desc())
            .limit(1)
        )
        if last and last.content.strip() == content.strip():
            return
        db.add(
            RulebookSnapshot(
                project_id=project.id,
                content=content,
                source=source,
                trigger=trigger,
                active_record_count=self.memory_service.count_active(db, project.id),
            )
        )

    async def get_rulebook(self, db: Session, project_id: str) -> dict[str, Any]:
        project = get_project(db, project_id)
        ctx = context_for(project)
        cached = {
            "content": project.rulebook_cache or "",
            "last_refreshed_at": iso(project.rulebook_cached_at),
            "source": "cache",
        }
        if not self.gateway.available:
            return {
                **cached,
                "is_stale": True,
                "status": "offline",
                "message": "Hindsight is offline — showing the cached Rulebook.",
            }
        try:
            model = await self.gateway.get_mental_model(ctx, project.rulebook_mental_model_id or RULEBOOK_MODEL_ID)
            if model is None:
                await self.gateway.ensure_rulebook(ctx)
                project.rulebook_mental_model_id = RULEBOOK_MODEL_ID
                db.commit()
                return {**cached, "is_stale": True, "status": "generating", "message": "Rulebook created; generating."}
        except HindsightUnavailable as exc:
            return {**cached, "is_stale": True, "status": "error", "message": exc.message}

        content = (model.get("content") or "").strip()
        generating = content.startswith("Generating content") or not content
        if not generating:
            refreshed = model.get("last_refreshed_at")
            changed = content != (project.rulebook_cache or "").strip()
            if changed:
                self._snapshot(db, project, content, "mental_model", "refresh")
                project.rulebook_cache = content
                project.rulebook_cached_at = _now()
                db.commit()
            return {
                "content": content,
                "last_refreshed_at": refreshed or iso(project.rulebook_cached_at),
                "last_memory_seen_at": model.get("last_memory_seen_at"),
                "is_stale": bool(model.get("is_stale")),
                "status": "ready",
                "source": "hindsight",
                "mental_model_id": model.get("id"),
            }
        return {
            **cached,
            "is_stale": True,
            "status": "generating",
            "message": "Hindsight is generating the Rulebook from the latest memory.",
        }

    async def refresh_rulebook(self, db: Session, project_id: str) -> dict[str, Any]:
        project = get_project(db, project_id)
        ctx = context_for(project)
        if not self.gateway.available:
            raise AppError(AppErrorCode.HINDSIGHT_UNAVAILABLE, "Hindsight is offline.", status_code=503)
        await self.gateway.ensure_rulebook(ctx)
        operation_id = await self.gateway.refresh_mental_model(ctx, project.rulebook_mental_model_id or RULEBOOK_MODEL_ID)
        AuditService.flush(db, ctx)
        return {"operation_id": operation_id, "status": "queued"}

    async def history(self, db: Session, project_id: str) -> list[dict[str, Any]]:
        project = get_project(db, project_id)
        items: list[dict[str, Any]] = []
        snapshots = db.scalars(
            select(RulebookSnapshot)
            .where(RulebookSnapshot.project_id == project.id)
            .order_by(RulebookSnapshot.refreshed_at.desc())
            .limit(30)
        ).all()
        for snap in snapshots:
            items.append(
                {
                    "changed_at": iso(snap.refreshed_at),
                    "content": snap.content,
                    "source": snap.source,
                    "active_record_count": snap.active_record_count,
                }
            )
        if self.gateway.available:
            try:
                for entry in await self.gateway.mental_model_history(
                    context_for(project), project.rulebook_mental_model_id or RULEBOOK_MODEL_ID
                ):
                    content = entry.get("previous_content") or entry.get("content")
                    if content and not any(i["content"].strip() == content.strip() for i in items):
                        items.append(
                            {
                                "changed_at": entry.get("changed_at") or entry.get("created_at"),
                                "content": content,
                                "source": "hindsight_history",
                                "active_record_count": None,
                            }
                        )
            except HindsightUnavailable:
                pass
        items.sort(key=lambda i: i["changed_at"] or "", reverse=True)
        return items

    # -------------------------------------------------------------------- ask
    async def ask(self, db: Session, project_id: str, question: str) -> dict[str, Any]:
        project = get_project(db, project_id)
        ctx = context_for(project)
        if not self.gateway.available:
            raise AppError(
                AppErrorCode.HINDSIGHT_UNAVAILABLE, "Ask is temporarily unavailable: Hindsight is offline.", status_code=503
            )
        try:
            result = await self.gateway.reflect(ctx, question, max_tokens=1200, budget="mid")
            if not result["memories"] and self.memory_service.count_active(db, project_id):
                # Hindsight Cloud occasionally returns an evidence-less answer; retry once.
                result = await self.gateway.reflect(ctx, question, max_tokens=1200, budget="mid")
        except HindsightUnavailable as exc:
            AuditService.flush(db, ctx)
            raise AppError(
                AppErrorCode.HINDSIGHT_UNAVAILABLE,
                "Ask is temporarily unavailable: Hindsight could not gather evidence.",
                status_code=503,
                details={"upstream": exc.message},
            ) from exc

        unit_ids = [m["id"] for m in result["memories"] if m.get("id")]
        mapping = await self.gateway.resolve_units(ctx, unit_ids) if unit_ids else {}
        AuditService.flush(db, ctx)
        record_ids: list[str] = []
        facts = []
        for m in result["memories"]:
            rids = mapping.get(m.get("id"), [])
            facts.append(
                {"id": m.get("id"), "text": m.get("text"), "type": m.get("type"), "record_ids": rids}
            )
            for rid in rids:
                if rid not in record_ids:
                    record_ids.append(rid)
        records = []
        for rid in record_ids:
            record = db.get(MemoryRecord, rid)
            if record and record.project_id == project_id:
                records.append(record_ref(record))
        return {
            "question": question,
            "answer": result["answer"],
            "based_on": records,
            "facts": facts,
            "guardrails": [{"name": d.get("name"), "content": d.get("content")} for d in result["directives"]],
            "latency_ms": result["latency_ms"],
        }

    # ----------------------------------------------------------------- export
    def export(self, db: Session, project_id: str, fmt: str = "claude_md") -> dict[str, Any]:
        """Export the governed Rulebook as CLAUDE.md or .cursorrules (complements static rule files)."""
        project = get_project(db, project_id)
        records = self.memory_service.get_active_records(db, project_id)
        by_area: dict[str, list[MemoryRecord]] = defaultdict(list)
        for r in records:
            by_area[r.area or "general"].append(r)
        lines = [
            f"# {project.name} — engineering rules",
            "",
            (
                f"_Exported from ProjectPulse on {_now().date().isoformat()}. "
                f"{len(records)} active, human-reviewed records. Superseded and retracted rules are excluded._"
            ),
            "",
        ]
        if project.tech_stack:
            lines += [f"Stack: {project.tech_stack}", ""]
        for area in sorted(by_area):
            lines.append(f"## {area.replace('-', ' ').title()}")
            lines.append("")
            for r in sorted(by_area[area], key=lambda x: (-x.importance, x.decided_at)):
                label = MEMORY_TYPES[normalize_type(r.type)].label
                lines.append(f"- **{r.title}** ({label}, {r.pill}, decided {r.decided_at.date().isoformat()})")
                lines.append(f"  {r.statement}")
                if r.rationale:
                    lines.append(f"  _Why:_ {r.rationale}")
            lines.append("")
        lines += [
            "---",
            (
                "Before implementing a task, call the ProjectPulse `projectpulse_brief` MCP tool with the task, "
                "and run `projectpulse_check` on your output before you finish."
            ),
        ]
        filename = "CLAUDE.md" if fmt == "claude_md" else ".cursorrules"
        return {"filename": filename, "content": "\n".join(lines), "records": len(records)}

    @staticmethod
    def dumps(value: Any) -> str:
        return json.dumps(value, default=str)
