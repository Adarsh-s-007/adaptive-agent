"""ProjectContext and BankResolver: server-side bank resolution and isolation (Blueprint §7.2).

No endpoint accepts a bank ID from a client. Every Hindsight call takes a resolved
`ProjectContext`, never a raw bank string, so the wrong bank cannot be passed by accident.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.errors import AppError, AppErrorCode
from app.models.entities import Project


@dataclass
class ProjectContext:
    project_id: str
    bank_id: str
    project_name: str
    description: str = ""
    tech_stack: str = ""
    areas: list[str] = field(default_factory=list)
    bank_status: str = "ready"
    rulebook_mental_model_id: str | None = None
    isolation_blocked_count: int = 0
    # Audit events produced by gateway calls; services persist them with their DB session.
    events: list[dict] = field(default_factory=list)

    def assert_record_isolated(self, record_project_id: str | None) -> bool:
        """True when a retrieved item belongs to this project; counts and drops foreign items."""
        if record_project_id and record_project_id != self.project_id:
            self.isolation_blocked_count += 1
            self.events.append(
                {
                    "event_type": "ISOLATION_VIOLATION_BLOCKED",
                    "status": "error",
                    "detail": {"foreign_project_id": record_project_id},
                }
            )
            return False
        return True

    def audit(
        self,
        event_type: str,
        *,
        status: str = "ok",
        latency_ms: int | None = None,
        record_id: str | None = None,
        run_id: str | None = None,
        detail: dict | None = None,
    ) -> None:
        self.events.append(
            {
                "event_type": event_type,
                "status": status,
                "latency_ms": latency_ms,
                "record_id": record_id,
                "run_id": run_id,
                "detail": detail or {},
            }
        )

    def assert_writable(self, record_project_id: str, bank_id: str) -> None:
        """Write guard (§7.2 control 3)."""
        if record_project_id != self.project_id or bank_id != self.bank_id:
            raise AppError(
                code=AppErrorCode.ISOLATION_VIOLATION,
                message="Refused to write a record into another project's memory bank.",
                status_code=500,
            )


def get_project(db: Session, project_id: str) -> Project:
    try:
        uuid.UUID(str(project_id))
    except (ValueError, TypeError) as exc:
        raise AppError(
            AppErrorCode.VALIDATION_FAILED, "project_id must be a UUID.", status_code=422
        ) from exc
    project = db.get(Project, project_id)
    if not project:
        raise AppError(AppErrorCode.NOT_FOUND, "Project not found.", status_code=404)
    return project


def context_for(project: Project) -> ProjectContext:
    try:
        areas = json.loads(project.areas_json or "[]")
    except ValueError:
        areas = []
    return ProjectContext(
        project_id=project.id,
        bank_id=project.hindsight_bank_id,
        project_name=project.name,
        description=project.description or "",
        tech_stack=project.tech_stack or "",
        areas=areas if isinstance(areas, list) else [],
        bank_status=project.bank_status or "ready",
        rulebook_mental_model_id=project.rulebook_mental_model_id,
    )


class BankResolver:
    """The single place that maps a project UUID to its Hindsight bank."""

    @staticmethod
    def resolve(db: Session, project_id: str, require_ready: bool = False) -> ProjectContext:
        project = get_project(db, project_id)
        if require_ready and project.bank_status != "ready":
            raise AppError(
                code=AppErrorCode.PROJECT_NOT_READY,
                message=(
                    f"Project memory bank is '{project.bank_status}'. "
                    "Retry provisioning in Settings."
                ),
                status_code=409,
            )
        return context_for(project)
