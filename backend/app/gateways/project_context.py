"""ProjectContext and BankResolver for server-side bank and isolation guarantees (HS-3)."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.project_memory_service import project_or_404
from sqlalchemy.orm import Session


@dataclass
class ProjectContext:
    project_id: str
    bank_id: str
    project_name: str
    description: str = ""
    isolation_blocked_count: int = 0

    def assert_record_isolated(self, record_project_id: str | None) -> bool:
        """Assert that a retrieved memory actually belongs to this project.
        
        Returns True if valid. If mismatched, increments isolation_blocked_count and returns False.
        """
        if record_project_id and record_project_id != self.project_id:
            self.isolation_blocked_count += 1
            return False
        return True


class BankResolver:
    """Resolves project context server-side. Never accepts client-supplied bank IDs (I3)."""

    @staticmethod
    def resolve(db: Session, project_id: str, require_ready: bool = False) -> ProjectContext:
        project = project_or_404(db, project_id)
        return ProjectContext(
            project_id=project.id,
            bank_id=project.hindsight_bank_id,
            project_name=project.name,
            description=project.description or "",
        )
