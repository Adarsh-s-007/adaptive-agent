"""ProjectContext and BankResolver (isolation control 1). Owner: P2."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.db.models import Project


@dataclass(frozen=True)
class ProjectContext:
    project_id: uuid.UUID
    bank_id: str
    name: str


async def resolve(
    db: AsyncSession, project_id: uuid.UUID, *, require_ready: bool = True
) -> ProjectContext:
    project = await db.get(Project, project_id)
    if project is None:
        raise AppError(ErrorCode.NOT_FOUND, "Project not found.")
    if require_ready and project.bank_status != "ready":
        raise AppError(ErrorCode.PROJECT_NOT_READY, f"Project bank is {project.bank_status}.")
    return ProjectContext(
        project_id=project.id, bank_id=project.hindsight_bank_id, name=project.name
    )
