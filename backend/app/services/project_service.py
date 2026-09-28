"""Project Provisioning, Bank Lifecycle, Rulebook and Ask Service (HS-4, RF-1, RF-2)."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError, AppErrorCode
from app.core.ids import generate_uuidv7
from app.gateways.hindsight_gateway import HindsightGateway
from app.gateways.project_context import BankResolver, ProjectContext
from app.models.entities import Project
from app.services.project_memory_service import project_or_404


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned[:30] or "proj"


def generate_bank_id(project_name: str, project_id: str) -> str:
    """Format: pp_<slug>_<hash8> per Blueprint §15.2 / HS-4."""
    slug = slugify(project_name)
    hash8 = hashlib.sha256(project_id.encode()).hexdigest()[:8]
    return f"pp_{slug}_{hash8}"


class ProjectService:
    """Manages project memory spaces, bank provisioning, and Rulebook synthesis."""

    def __init__(self, gateway: HindsightGateway | None = None) -> None:
        self.gateway = gateway or HindsightGateway()

    async def create_project(
        self,
        db: Session,
        name: str,
        description: str = "",
    ) -> Project:
        """Create a new project and provision its isolated Hindsight bank."""
        project_id = generate_uuidv7()
        bank_id = generate_bank_id(name, project_id)

        project = Project(
            id=project_id,
            name=name.strip(),
            description=description.strip(),
            hindsight_bank_id=bank_id,
            bank_status="provisioning",
            rulebook_cache=None,
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        # Provision Hindsight bank
        ctx = ProjectContext(
            project_id=project.id,
            bank_id=project.hindsight_bank_id,
            project_name=project.name,
            description=project.description,
        )

        try:
            await self.gateway.provision_bank(
                ctx=ctx,
                project_name=project.name,
                description=project.description,
            )
            project.bank_status = "ready"
        except Exception:
            project.bank_status = "error"

        db.commit()
        db.refresh(project)
        return project

    async def provision_project(self, db: Session, project_id: str) -> Project:
        """Idempotent retry for bank provisioning (HS-4)."""
        project = project_or_404(db, project_id)
        if project.bank_status == "ready":
            return project

        project.bank_status = "provisioning"
        db.commit()

        ctx = ProjectContext(
            project_id=project.id,
            bank_id=project.hindsight_bank_id,
            project_name=project.name,
            description=project.description,
        )

        try:
            await self.gateway.provision_bank(
                ctx=ctx,
                project_name=project.name,
                description=project.description,
            )
            project.bank_status = "ready"
        except Exception as exc:
            project.bank_status = "error"
            db.commit()
            raise AppError(
                code=AppErrorCode.HINDSIGHT_UNAVAILABLE,
                message=f"Bank provisioning failed: {exc!s}",
                status_code=502,
            )

        db.commit()
        db.refresh(project)
        return project

    async def get_rulebook(self, db: Session, project_id: str) -> dict[str, Any]:
        """Fetch Rulebook text, using cache when available (RF-2)."""
        project = project_or_404(db, project_id)
        if project.rulebook_cache:
            return {"project_id": project.id, "rulebook": project.rulebook_cache, "cached": True}

        ctx = BankResolver.resolve(db, project_id)
        rulebook_text = await self.gateway.rulebook_get(ctx)

        project.rulebook_cache = rulebook_text
        db.commit()
        return {"project_id": project.id, "rulebook": rulebook_text, "cached": False}

    async def refresh_rulebook(self, db: Session, project_id: str) -> dict[str, Any]:
        """Force refresh of Rulebook synthesis from memory records (RF-2)."""
        project = project_or_404(db, project_id)
        ctx = BankResolver.resolve(db, project_id)

        rulebook_text = await self.gateway.rulebook_get(ctx)
        project.rulebook_cache = rulebook_text
        db.commit()
        return {"project_id": project.id, "rulebook": rulebook_text, "refreshed": True}

    async def ask(self, db: Session, project_id: str, question: str) -> dict[str, Any]:
        """Ask question to project memory space with citation mapping (RF-1)."""
        ctx = BankResolver.resolve(db, project_id)
        return await self.gateway.ask(ctx, question)
