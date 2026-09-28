"""Demo data loader (Blueprint §25). Seeds go through the same record/retain path a human uses.

Only the inputs are fixed in advance: records, transcripts, demo tasks and eval labels.
Extraction, recall, generation and checks always run live.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import invalid
from app.db.governed_models import (
    CheckRun,
    ComparisonRun,
    EvalRun,
    MemoryCandidate,
    MemoryRecord,
    RecordEvidence,
    RulebookSnapshot,
    SessionTurn,
    TaskRun,
)
from app.gateways.hindsight_gateway import HindsightGateway, HindsightUnavailable
from app.gateways.project_context import context_for, get_project
from app.models.entities import AgentSession, Project
from app.services.audit_service import AuditService
from app.services.governed_memory_service import GovernedMemoryService
from app.services.project_service import ProjectService
from app.services.session_service import SessionService
from app.services.transcript_parser import split_front_matter

SEED_DIR = Path(__file__).resolve().parents[3] / "seed"
DATASETS = ("apexcart", "ledgerlite")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def demo_tasks() -> list[dict[str, Any]]:
    path = SEED_DIR / "demo_tasks.json"
    return _load(path) if path.exists() else []


def eval_set(name: str = "default") -> dict[str, Any]:
    path = SEED_DIR / "eval_tasks.json"
    if not path.exists():
        raise invalid("Eval set not found.")
    data = _load(path)
    if data.get("set") != name:
        raise invalid(f"Unknown eval set '{name}'.")
    return data


class SeedService:
    def __init__(
        self,
        memory_service: GovernedMemoryService | None = None,
        project_service: ProjectService | None = None,
        session_service: SessionService | None = None,
    ) -> None:
        self.memory_service = memory_service or GovernedMemoryService()
        self.gateway: HindsightGateway = self.memory_service.gateway
        self.project_service = project_service or ProjectService(self.gateway)
        self.session_service = session_service or SessionService()

    @staticmethod
    def profile(dataset: str) -> dict[str, Any]:
        if dataset not in DATASETS:
            raise invalid(f"Unknown dataset '{dataset}'. Use one of {', '.join(DATASETS)}.")
        return _load(SEED_DIR / dataset / "project.json")

    async def ensure_project(self, db: Session, dataset: str, *, reset: bool = False) -> tuple[Project, bool]:
        """Find or create the demo project; with reset, wipe its governance data and bank."""
        profile = self.profile(dataset)
        project = db.scalar(select(Project).where(func.lower(Project.name) == profile["name"].lower()))
        created = False
        if project is None:
            project = await self.project_service.create_project(
                db,
                profile["name"],
                profile.get("description", ""),
                profile.get("tech_stack", ""),
                profile.get("areas", []),
            )
            created = True
        elif reset:
            await self.reset_project(db, project)
        return project, created

    async def reset_project(self, db: Session, project: Project) -> None:
        pid = project.id
        session_ids = [s for (s,) in db.execute(select(AgentSession.id).where(AgentSession.project_id == pid)).all()]
        record_ids = [r for (r,) in db.execute(select(MemoryRecord.id).where(MemoryRecord.project_id == pid)).all()]
        run_ids = [r for (r,) in db.execute(select(TaskRun.id).where(TaskRun.project_id == pid)).all()]
        db.execute(delete(CheckRun).where(CheckRun.project_id == pid))
        db.execute(delete(ComparisonRun).where(ComparisonRun.project_id == pid))
        if run_ids:
            db.execute(delete(TaskRun).where(TaskRun.id.in_(run_ids)))
        db.execute(delete(MemoryCandidate).where(MemoryCandidate.project_id == pid))
        if record_ids:
            db.execute(delete(RecordEvidence).where(RecordEvidence.record_id.in_(record_ids)))
            db.execute(
                MemoryRecord.__table__.update()
                .where(MemoryRecord.id.in_(record_ids))
                .values(supersedes_id=None, superseded_by_id=None)
            )
            db.execute(delete(MemoryRecord).where(MemoryRecord.id.in_(record_ids)))
        if session_ids:
            db.execute(delete(SessionTurn).where(SessionTurn.session_id.in_(session_ids)))
            db.execute(
                delete(AgentSession).where(
                    AgentSession.id.in_(session_ids),
                    AgentSession.source.in_(("workspace", "import", "seed", "mcp")),
                )
            )
        db.execute(delete(RulebookSnapshot).where(RulebookSnapshot.project_id == pid))
        db.execute(delete(EvalRun).where(EvalRun.project_id == pid))
        project.rulebook_cache = None
        project.rulebook_cached_at = None
        db.commit()
        if self.gateway.available:
            ctx = context_for(project)
            try:
                await self.gateway.delete_bank(ctx)
            except HindsightUnavailable:
                pass
        await self.project_service.provision_project(db, pid, force=True)
        AuditService.log(db, pid, "RESET", detail={"note": "Demo data reset"}, commit=True)

    async def seed_dataset(self, db: Session, project_id: str, dataset: str = "apexcart") -> dict[str, Any]:
        """Seed records (retained through the normal path) and unextracted transcripts."""
        project = get_project(db, project_id)
        if dataset not in DATASETS:
            raise invalid(f"Unknown dataset '{dataset}'.")
        base = SEED_DIR / dataset
        existing_titles = {
            t for (t,) in db.execute(select(MemoryRecord.title).where(MemoryRecord.project_id == project.id)).all()
        }
        created = 0
        skipped = 0
        items = [i for i in _load(base / "records.json")]
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            if item["title"] in existing_titles:
                skipped += 1
                continue
            groups.setdefault(item.get("session") or item["title"], []).append(item)

        for session_title, group in groups.items():
            # One historical session per decision meeting; each quote is a human turn.
            transcript = "\n\n".join(
                f"Human ({item.get('decided_by', 'Tech lead')}): {item['quote']}" for item in group
            )
            session = self.session_service.import_transcript(
                db,
                project.id,
                title=session_title,
                text=transcript,
                developer=group[0].get("decided_by"),
                agent_label="Earlier session",
                occurred_at=_dt(group[0].get("decided_at")),
                source="seed",
            )
            session.status = "extracted"
            db.commit()
            for turn_no, item in enumerate(group, start=1):
                await self._seed_record(db, project.id, session.id, item, turn_no)
                created += 1

        transcripts = await self._seed_transcripts(db, project.id, base)
        AuditService.log(
            db,
            project.id,
            "SEED",
            detail={"dataset": dataset, "records": created, "skipped": skipped, "transcripts": transcripts},
            commit=True,
        )
        unsynced = db.scalar(
            select(func.count())
            .select_from(MemoryRecord)
            .where(MemoryRecord.project_id == project.id, MemoryRecord.retain_state != "retained")
        )
        return {
            "project_id": project.id,
            "dataset": dataset,
            "records_created": created,
            "records_skipped": skipped,
            "transcripts_imported": transcripts,
            "unsynced_records": int(unsynced or 0),
            # Legacy keys.
            "seeded": created,
            "records": created,
        }

    async def _seed_record(self, db: Session, project_id: str, session_id: str, item: dict[str, Any], turn_no: int):
        return await self.memory_service.create_record(
            db,
            project_id,
            title=item["title"],
            statement=item["statement"],
            memory_type=item["type"],
            rationale=item.get("rationale"),
            area=item.get("area"),
            importance=item.get("importance"),
            source_session_id=session_id,
            evidence_quote=item.get("quote"),
            tags=[f"seed:{item['key'].lower()}"],
            check_patterns=item.get("check_patterns") or None,
            applies_to=item.get("applies_to"),
            decided_at=_dt(item.get("decided_at")),
            source="seed",
            approved_by=item.get("decided_by"),
            evidence_turn=turn_no,
            retain_async=True,
        )

    async def _seed_transcripts(self, db: Session, project_id: str, base: Path) -> int:
        """Import the unextracted demo transcripts; extraction runs live during the demo."""
        transcripts = 0
        tdir = base / "transcripts"
        if not tdir.exists():
            return 0
        existing_sessions = {
            t for (t,) in db.execute(select(AgentSession.title).where(AgentSession.project_id == project_id)).all()
        }
        for path in sorted(tdir.glob("*.md")):
            meta, body = split_front_matter(path.read_text(encoding="utf-8"))
            title = f"{meta.get('id', path.stem)} · {meta.get('title', path.stem)}"
            if title in existing_sessions:
                continue
            self.session_service.import_transcript(
                db,
                project_id,
                title=title,
                text=body,
                developer=meta.get("developer"),
                agent_label=meta.get("agent", "Coding agent"),
                occurred_at=_dt(meta.get("occurred_at")),
                source="import",
            )
            transcripts += 1
        return transcripts

    async def seed(self, db: Session, dataset: str, *, reset: bool = False) -> dict[str, Any]:
        project, created = await self.ensure_project(db, dataset, reset=reset)
        result = await self.seed_dataset(db, project.id, dataset)
        db.refresh(project)
        return {**result, "project_created": created, "bank_status": project.bank_status, "project_name": project.name}
