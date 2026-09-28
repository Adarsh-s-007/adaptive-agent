"""Projects: creation with automatic Hindsight bank provisioning, status and stats (§7.3, §15.2)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import conflict, invalid
from app.core.ids import generate_uuidv7
from app.db.governed_models import (
    AuditEvent,
    ComparisonRun,
    MemoryCandidate,
    MemoryRecord,
)
from app.gateways.hindsight_gateway import HindsightGateway, HindsightUnavailable
from app.gateways.project_context import context_for, get_project
from app.models.entities import AgentSession, Project
from app.services.audit_service import AuditService
from app.services.serializers import iso, project_dto


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned[:30].strip("-") or "project"


def generate_bank_id(project_name: str, project_id: str) -> str:
    """`pp_<slug>_<hash8>`: two projects with the same slug still get distinct banks (§7.1)."""
    slug = slugify(project_name).replace("-", "_")
    hash8 = hashlib.sha256(project_id.encode()).hexdigest()[:8]
    return f"pp_{slug}_{hash8}"


class ProjectService:
    def __init__(self, gateway: HindsightGateway | None = None) -> None:
        from app.gateways.hindsight_gateway import get_hindsight_gateway

        self.gateway = gateway or get_hindsight_gateway()

    async def create_project(
        self,
        db: Session,
        name: str,
        description: str = "",
        tech_stack: str = "",
        areas: list[str] | None = None,
        *,
        provision: bool = True,
    ) -> Project:
        name = name.strip()
        if len(name) < 2:
            raise invalid("Project name must be at least 2 characters.")
        if db.scalar(select(Project).where(func.lower(Project.name) == name.lower())):
            raise conflict("A project with that name already exists.")
        project_id = generate_uuidv7()
        clean_areas = []
        for area in areas or []:
            slug = slugify(area)
            if slug and slug not in clean_areas:
                clean_areas.append(slug)
        project = Project(
            id=project_id,
            name=name,
            slug=slugify(name),
            description=(description or "").strip(),
            tech_stack=(tech_stack or "").strip(),
            areas_json=json.dumps(clean_areas[:20]),
            hindsight_bank_id=generate_bank_id(name, project_id),
            bank_status="provisioning",
        )
        db.add(project)
        AuditService.log(db, project.id, "PROJECT_CREATED", detail={"name": name, "bank_id": project.hindsight_bank_id})
        db.commit()
        db.refresh(project)
        if provision:
            await self._provision(db, project)
        return project

    async def _provision(self, db: Session, project: Project) -> Project:
        ctx = context_for(project)
        project.bank_status = "provisioning"
        db.commit()
        try:
            result = await self.gateway.provision_bank(ctx, project.name, project.description)
            project.bank_status = "ready"
            project.bank_error = None
            project.provisioned_at = datetime.now(timezone.utc)
            project.rulebook_mental_model_id = result.get("mental_model_id") or "rulebook"
        except HindsightUnavailable as exc:
            project.bank_status = "error"
            project.bank_error = exc.message
            ctx.audit("PROVISION", status="error", detail={"error": exc.message})
        AuditService.flush(db, ctx, commit=False)
        db.commit()
        db.refresh(project)
        return project

    async def provision_project(self, db: Session, project_id: str, *, force: bool = False) -> Project:
        """Idempotent: re-running provisioning on a ready bank only fills in what is missing."""
        project = get_project(db, project_id)
        if project.bank_status == "ready" and not force:
            return project
        return await self._provision(db, project)

    def list_projects(self, db: Session) -> list[dict[str, Any]]:
        projects = db.scalars(select(Project).order_by(Project.created_at.desc())).all()
        return [project_dto(p, self.stats(db, p.id)) for p in projects]

    def detail(self, db: Session, project_id: str) -> dict[str, Any]:
        project = get_project(db, project_id)
        return project_dto(project, self.stats(db, project.id, full=True))

    def stats(self, db: Session, project_id: str, *, full: bool = False) -> dict[str, Any]:
        by_status = dict(
            db.execute(
                select(MemoryRecord.status, func.count())
                .where(MemoryRecord.project_id == project_id)
                .group_by(MemoryRecord.status)
            ).all()
        )
        pending = int(
            db.scalar(
                select(func.count())
                .select_from(MemoryCandidate)
                .where(MemoryCandidate.project_id == project_id, MemoryCandidate.status == "pending")
            )
            or 0
        )
        last_event = db.scalar(select(func.max(AuditEvent.created_at)).where(AuditEvent.project_id == project_id))
        stats: dict[str, Any] = {
            "active_records": int(by_status.get("active", 0)),
            "superseded_records": int(by_status.get("superseded", 0)),
            "retracted_records": int(by_status.get("retracted", 0)),
            "pending_candidates": pending,
            "last_activity_at": iso(last_event),
        }
        if full:
            by_type = dict(
                db.execute(
                    select(MemoryRecord.type, func.count())
                    .where(MemoryRecord.project_id == project_id, MemoryRecord.status == "active")
                    .group_by(MemoryRecord.type)
                ).all()
            )
            unsynced = int(
                db.scalar(
                    select(func.count())
                    .select_from(MemoryRecord)
                    .where(MemoryRecord.project_id == project_id, MemoryRecord.retain_state != "retained")
                )
                or 0
            )
            sessions = int(
                db.scalar(
                    select(func.count())
                    .select_from(AgentSession)
                    .where(
                        AgentSession.project_id == project_id,
                        AgentSession.source.in_(("workspace", "import", "seed", "mcp")),
                    )
                )
                or 0
            )
            comparisons = int(
                db.scalar(
                    select(func.count()).select_from(ComparisonRun).where(ComparisonRun.project_id == project_id)
                )
                or 0
            )
            stats.update(
                {
                    "active_by_type": {k: int(v) for k, v in by_type.items()},
                    "unsynced_records": unsynced,
                    "sessions": sessions,
                    "comparisons": comparisons,
                    "isolation_violations_blocked": AuditService.isolation_violations(db, project_id),
                }
            )
        return stats

    async def bank_summary(self, db: Session, project_id: str) -> dict[str, Any]:
        """Settings view: bank configuration, directives and Hindsight stats (best effort)."""
        project = get_project(db, project_id)
        ctx = context_for(project)
        summary: dict[str, Any] = {
            "bank_id": project.hindsight_bank_id,
            "bank_status": project.bank_status,
            "bank_error": project.bank_error,
            "available": self.gateway.available,
            "config": None,
            "directives": [],
            "stats": None,
        }
        if not self.gateway.available:
            return summary
        try:
            config = await self.gateway.get_bank_config(ctx)
            summary["config"] = {
                k: config.get(k)
                for k in (
                    "retain_mission",
                    "retain_extraction_mode",
                    "observations_mission",
                    "reflect_mission",
                    "enable_observations",
                    "enable_auto_consolidation",
                    "memory_defense",
                    "disposition_skepticism",
                    "disposition_literalism",
                    "disposition_empathy",
                )
            }
            summary["directives"] = [
                {"name": d.get("name"), "content": d.get("content"), "is_active": d.get("is_active", True)}
                for d in await self.gateway.list_directives(ctx)
            ]
            summary["stats"] = await self.gateway.bank_stats(ctx)
        except HindsightUnavailable as exc:
            summary["error"] = exc.message
        return summary
