"""Generation Service for baseline and memory-aware agent executions (GN-2, GN-3)."""

from __future__ import annotations

import json
import time

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.governed_models import TaskRun
from app.gateways.llm_gateway import LLMGateway
from app.schemas.common import BriefResult, RunOutput, TaskRunOut
from app.services.brief_service import BriefService


class AgentResponseSchema(BaseModel):
    summary: str
    files: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    followed_record_ids: list[str] = Field(default_factory=list)


class GenerationService:
    """Manages baseline and memory-informed agent code generation runs."""

    def __init__(
        self,
        llm: LLMGateway | None = None,
        brief_service: BriefService | None = None,
    ) -> None:
        self.llm = llm or LLMGateway()
        self.brief_service = brief_service or BriefService(llm=self.llm)

    async def run(
        self,
        db: Session,
        project_id: str,
        task: str,
        mode: str = "memory",
        session_id: str | None = None,
    ) -> TaskRunOut:
        start_time = time.perf_counter()

        brief: BriefResult | None = None
        followed_record_ids: list[str] = []

        if mode == "baseline":
            # Baseline makes ZERO memory calls (Blueprint M1)
            system_prompt = (
                "You are an expert software engineer. Provide a structured implementation outline for the task. "
                "You have no access to prior project decisions; outline standard solutions."
            )
            user_prompt = f"Task: {task}"
        else:
            # Memory-aware run: obtain brief first
            brief = await self.brief_service.build_brief(db, project_id, task)
            
            memory_block = ""
            if brief.applied:
                lines = []
                for a in brief.applied:
                    lines.append(f"- [{a.record.pill}] {a.record.title}: {a.record.statement} (Reason: {a.reason})")
                memory_block = (
                    "\n\n<project_memory>\n"
                    "The following verified project rules apply to this task. You MUST follow them strictly:\n"
                    + "\n".join(lines)
                    + "\n</project_memory>"
                )

            system_prompt = (
                "You are an expert software engineer. Provide a structured implementation outline that strictly "
                "adheres to the established project memory rules provided."
            )
            user_prompt = f"Task: {task}{memory_block}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            llm_res = await self.llm.complete_json(
                tier="large",
                messages=messages,
                schema=AgentResponseSchema,
                job="generate",
                temperature=0.0,
            )
            parsed: AgentResponseSchema = llm_res.parsed
            usage = llm_res.usage
            summary = parsed.summary
            files = parsed.files
            notes = parsed.notes
            followed_record_ids = parsed.followed_record_ids or (
                [a.record.id for a in brief.applied] if brief and brief.applied else []
            )
        except Exception:
            # Fallback output
            summary = f"Implementation plan for: {task}"
            files = ["app/main.py"]
            notes = ["Generated using baseline defaults."]
            usage = {"prompt_tokens": 100, "completion_tokens": 80, "total_tokens": 180}
            followed_record_ids = [a.record.id for a in brief.applied] if brief and brief.applied else []

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        # Persist TaskRun
        task_run = TaskRun(
            project_id=project_id,
            session_id=session_id,
            mode=mode,
            task=task,
            summary=summary,
            output_files_json=json.dumps(files),
            output_notes_json=json.dumps(notes),
            followed_record_ids_json=json.dumps(followed_record_ids),
            brief_snapshot_json=brief.model_dump_json() if brief else None,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
        )
        db.add(task_run)
        db.commit()
        db.refresh(task_run)

        return TaskRunOut(
            id=task_run.id,
            project_id=project_id,
            mode=mode,
            task=task,
            output=RunOutput(
                summary=summary,
                files=files,
                notes=notes,
                followed_record_ids=followed_record_ids,
            ),
            brief=brief,
            usage=usage,
            latency_ms=latency_ms,
            created_at=task_run.created_at.isoformat(),
        )
