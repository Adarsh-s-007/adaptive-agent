"""Knowledge-evolution timeline: approvals, supersessions, retractions, sessions, Rulebook refreshes."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.governed_models import ComparisonRun, MemoryRecord, RulebookSnapshot
from app.models.entities import AgentSession
from app.services.serializers import iso, loads, record_ref


class TimelineService:
    def get_timeline(self, db: Session, project_id: str, limit: int = 100) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        records = db.scalars(select(MemoryRecord).where(MemoryRecord.project_id == project_id)).all()
        by_id = {r.id: r for r in records}

        for r in records:
            if r.supersedes_id and r.supersedes_id in by_id:
                old = by_id[r.supersedes_id]
                items.append(
                    {
                        "id": f"sup-{r.id}",
                        "kind": "superseded",
                        "at": iso(r.decided_at),
                        "title": f"{old.pill} superseded by {r.pill}",
                        "summary": r.title,
                        "record": record_ref(r),
                        "previous": record_ref(old),
                        "actor": r.approved_by,
                    }
                )
            else:
                items.append(
                    {
                        "id": f"rec-{r.id}",
                        "kind": "seeded" if r.source == "seed" else "approved",
                        "at": iso(r.decided_at),
                        "title": r.title,
                        "summary": r.statement,
                        "record": record_ref(r),
                        "actor": r.approved_by,
                    }
                )
            if r.status == "retracted":
                items.append(
                    {
                        "id": f"ret-{r.id}",
                        "kind": "retracted",
                        "at": iso(r.retired_at or r.updated_at),
                        "title": f"{r.pill} retracted",
                        "summary": r.retract_reason or "Marked wrong; removed from recall.",
                        "record": record_ref(r),
                    }
                )

        for s in db.scalars(
            select(AgentSession).where(
                AgentSession.project_id == project_id,
                AgentSession.source.in_(("workspace", "import", "seed", "mcp")),
            )
        ).all():
            stats = loads(s.extraction_stats_json, {})
            items.append(
                {
                    "id": f"ses-{s.id}",
                    "kind": "session",
                    "at": iso(s.occurred_at or s.created_at),
                    "title": s.title or s.task,
                    "summary": (
                        f"{s.developer or 'Developer'} · {s.agent_label or s.agent_name} · "
                        + (
                            f"{stats.get('accepted', 0)} candidates, {stats.get('auto_rejected', 0) + stats.get('discarded', 0)} filtered"
                            if s.status == "extracted"
                            else s.status or "closed"
                        )
                    ),
                    "session_id": s.id,
                    "status": s.status,
                }
            )

        for snap in db.scalars(select(RulebookSnapshot).where(RulebookSnapshot.project_id == project_id)).all():
            items.append(
                {
                    "id": f"rb-{snap.id}",
                    "kind": "rulebook_refreshed",
                    "at": iso(snap.refreshed_at),
                    "title": "Project Rulebook refreshed",
                    "summary": f"Synthesised from {snap.active_record_count or 0} active records.",
                }
            )

        for c in db.scalars(
            select(ComparisonRun).where(ComparisonRun.project_id == project_id, ComparisonRun.status == "completed")
        ).all():
            summary = loads(c.summary_json, {})
            items.append(
                {
                    "id": f"cmp-{c.id}",
                    "kind": "comparison",
                    "at": iso(c.completed_at or c.created_at),
                    "title": "Compare run",
                    "summary": (
                        f"Violations {summary.get('mean_violations_baseline', c.violations_baseline)} → "
                        f"{summary.get('mean_violations_memory', c.violations_memory)} · {c.task[:80]}"
                    ),
                    "comparison_id": c.id,
                }
            )

        items.sort(key=lambda i: i.get("at") or "", reverse=True)
        return items[:limit]
