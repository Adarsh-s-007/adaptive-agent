"""Sessions, turns, transcript import and Workspace chat (Blueprint §9.3, §13.3)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, AppErrorCode, conflict, invalid, not_found
from app.db.governed_models import MemoryCandidate, SessionTurn
from app.gateways.project_context import get_project
from app.models.entities import AgentSession
from app.services.audit_service import AuditService
from app.services.generation_service import GenerationService
from app.services.serializers import session_dto, turn_dto
from app.services.signals import TranscriptPreparer
from app.services.transcript_parser import TranscriptParser


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SessionService:
    def __init__(self, generation: GenerationService | None = None) -> None:
        self.generation = generation or GenerationService()

    # ------------------------------------------------------------------ reads
    def get(self, db: Session, project_id: str, session_id: str) -> AgentSession:
        session = db.get(AgentSession, session_id)
        if not session or session.project_id != project_id:
            raise not_found("Session")
        return session

    def turns(self, db: Session, session_id: str) -> list[SessionTurn]:
        return list(
            db.scalars(
                select(SessionTurn).where(SessionTurn.session_id == session_id).order_by(SessionTurn.turn_index)
            ).all()
        )

    def list(self, db: Session, project_id: str, include_legacy: bool = False) -> list[dict[str, Any]]:
        get_project(db, project_id)
        query = select(AgentSession).where(AgentSession.project_id == project_id)
        if not include_legacy:
            query = query.where(AgentSession.source.in_(("workspace", "import", "seed", "mcp")))
        sessions = db.scalars(query.order_by(AgentSession.created_at.desc()).limit(200)).all()
        pending = dict(
            db.execute(
                select(MemoryCandidate.session_id, func.count())
                .where(MemoryCandidate.project_id == project_id, MemoryCandidate.status == "pending")
                .group_by(MemoryCandidate.session_id)
            ).all()
        )
        out = []
        for s in sessions:
            dto = session_dto(s)
            dto["pending_candidates"] = int(pending.get(s.id, 0))
            out.append(dto)
        return out

    def detail(self, db: Session, project_id: str, session_id: str) -> dict[str, Any]:
        session = self.get(db, project_id, session_id)
        return session_dto(session, turns=self.turns(db, session_id))

    # ---------------------------------------------------------------- writes
    def create(
        self,
        db: Session,
        project_id: str,
        *,
        title: str,
        developer: str | None = None,
        agent_label: str | None = None,
        source: str = "workspace",
    ) -> AgentSession:
        get_project(db, project_id)
        session = AgentSession(
            project_id=project_id,
            agent_name=(agent_label or "ProjectPulse agent")[:120],
            task=title,
            title=title[:200],
            developer=(developer or "Developer")[:120],
            agent_label=(agent_label or "ProjectPulse agent")[:120],
            source=source,
            status="open",
            occurred_at=_now(),
            turn_count=0,
        )
        db.add(session)
        AuditService.log(db, project_id, "SESSION_STARTED", actor=developer, detail={"title": title})
        db.commit()
        db.refresh(session)
        return session

    def _append_turn(
        self,
        db: Session,
        session: AgentSession,
        role: str,
        content: str,
        *,
        speaker: str | None = None,
        run_id: str | None = None,
        meta: dict | None = None,
    ) -> SessionTurn:
        last = db.scalar(select(func.max(SessionTurn.turn_index)).where(SessionTurn.session_id == session.id)) or 0
        turn = SessionTurn(
            session_id=session.id,
            turn_index=last + 1,
            role=role,
            speaker=speaker,
            content=content,
            run_id=run_id,
            meta_json=json.dumps(meta or {}, default=str),
        )
        db.add(turn)
        session.turn_count = last + 1
        return turn

    def import_transcript(
        self,
        db: Session,
        project_id: str,
        *,
        title: str,
        text: str,
        developer: str | None = None,
        agent_label: str | None = None,
        occurred_at: datetime | None = None,
        format_hint: str = "markdown",
        source: str = "import",
    ) -> AgentSession:
        get_project(db, project_id)
        parsed = TranscriptParser.parse(text, format_hint)
        if not parsed:
            raise invalid("The transcript is empty.")
        prepared = TranscriptPreparer.prepare_turns(parsed)
        session = AgentSession(
            project_id=project_id,
            agent_name=(agent_label or "Imported agent")[:120],
            task=title,
            title=title[:200],
            developer=(developer or "Developer")[:120],
            agent_label=(agent_label or "Imported agent")[:120],
            source=source,
            status="closed",
            occurred_at=occurred_at or _now(),
            ended_at=occurred_at or _now(),
            turn_count=len(prepared),
        )
        db.add(session)
        db.flush()
        for t in prepared:
            db.add(
                SessionTurn(
                    session_id=session.id,
                    turn_index=t.turn_index,
                    role=t.role,
                    speaker=t.speaker,
                    content=t.content,
                )
            )
        AuditService.log(
            db, project_id, "SESSION_IMPORTED", actor=developer, detail={"title": title, "turns": len(prepared), "session_id": session.id}
        )
        db.commit()
        db.refresh(session)
        return session

    def close(self, db: Session, project_id: str, session_id: str) -> AgentSession:
        session = self.get(db, project_id, session_id)
        if session.status == "open":
            session.status = "closed"
            session.ended_at = _now()
            db.commit()
        return session

    async def send_message(
        self,
        db: Session,
        project_id: str,
        session_id: str,
        *,
        content: str,
        use_memory: bool = True,
        file_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        session = self.get(db, project_id, session_id)
        if session.status != "open":
            raise conflict("This session is closed. Start a new session to keep working.")
        if not getattr(self.generation.llm, "configured", True):
            raise AppError(
                AppErrorCode.LLM_UNAVAILABLE,
                "The Workspace agent needs an LLM. Set GROQ_API_KEY on the server.",
                status_code=503,
            )
        history = [{"role": t.role, "content": t.content} for t in self.turns(db, session_id)[-8:]]
        human = self._append_turn(db, session, "human", content.strip(), speaker=session.developer)
        db.commit()

        mode = "memory" if use_memory else "baseline"
        brief = None
        if use_memory:
            brief = await self.generation.brief_service.build_brief(db, project_id, content, file_paths)
            if brief.status == "memory_unavailable":
                mode = "baseline"
        run = await self.generation.run(
            db, project_id, content, mode=mode, session_id=session_id, history=history, brief=brief
        )
        if run.status != "ok":
            return {
                "human_turn": turn_dto(human),
                "assistant_turn": None,
                "run": run.model_dump(),
                "brief": brief.model_dump() if brief else None,
                "error": run.error,
            }
        agent_text = self._render_answer(run.output)
        agent = self._append_turn(
            db,
            session,
            "agent",
            agent_text,
            speaker=session.agent_label,
            run_id=run.id,
            meta={
                "mode": mode,
                "files": [f.model_dump() for f in run.output.files],
                "notes": run.output.notes,
                "followed_record_ids": run.output.followed_record_ids,
                "brief_status": brief.status if brief else None,
                "applied": [a.record.pill for a in brief.applied] if brief else [],
            },
        )
        db.commit()
        db.refresh(agent)
        return {
            "human_turn": turn_dto(human),
            "assistant_turn": turn_dto(agent),
            "run": run.model_dump(),
            "brief": brief.model_dump() if brief else None,
            "memory_used": mode == "memory",
        }

    @staticmethod
    def _render_answer(output) -> str:
        parts = [output.summary.strip()]
        for f in output.files:
            parts.append(f"\n**{f.path}**\n```{f.language}\n{f.content.rstrip()}\n```")
        if output.notes:
            parts.append("\n" + "\n".join(f"- {n}" for n in output.notes))
        return "\n".join(p for p in parts if p).strip()
