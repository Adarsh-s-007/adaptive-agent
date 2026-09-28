"""Generation for workspace turns, single runs and Compare (Blueprint §16.2).

The system prompt has four fixed layers; only layer 3 (the project memory block) differs
between baseline and memory runs. The baseline path makes zero Hindsight calls (M1).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.governed_models import MemoryRecord, TaskRun
from app.gateways.llm_gateway import LLMGateway
from app.gateways.project_context import BankResolver, ProjectContext
from app.prompts.schemas import GenerationOutput
from app.prompts.templates import GENERATE_ROLE, MEMORY_RULES, PROJECT_PROFILE
from app.schemas.common import BriefResult, GeneratedFileOut, RunOutput, TaskRunOut
from app.services.audit_service import AuditService
from app.services.brief_service import BriefService
from app.services.serializers import iso


@dataclass
class AssembledPrompt:
    system: str
    layers: dict[str, str]

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.system.encode()).hexdigest()


def assemble_system_prompt(ctx: ProjectContext, memory_block: str | None) -> AssembledPrompt:
    role = GENERATE_ROLE.format(project=ctx.project_name)
    profile = PROJECT_PROFILE.format(
        name=ctx.project_name,
        description=ctx.description or "—",
        tech_stack=ctx.tech_stack or "—",
        areas=", ".join(ctx.areas) or "—",
    )
    memory = f"{MEMORY_RULES}\n{memory_block}" if memory_block else ""
    layers = {"role": role, "profile": profile, "memory": memory}
    system = "\n\n".join(part for part in (role, profile, memory) if part)
    return AssembledPrompt(system=system, layers=layers)


class GenerationService:
    """Runs one generation in baseline or memory mode and persists the TaskRun."""

    def __init__(self, llm: LLMGateway | None = None, brief_service: BriefService | None = None) -> None:
        from app.gateways.llm_gateway import get_llm_gateway

        self.llm = llm or get_llm_gateway()
        self.brief_service = brief_service or BriefService(llm=self.llm)

    async def run(
        self,
        db: Session,
        project_id: str,
        task: str,
        mode: str = "memory",
        session_id: str | None = None,
        *,
        history: list[dict[str, str]] | None = None,
        comparison_id: str | None = None,
        repeat_index: int = 0,
        brief: BriefResult | None = None,
        file_paths: list[str] | None = None,
        raise_on_error: bool = False,
    ) -> TaskRunOut:
        started = time.perf_counter()
        ctx = BankResolver.resolve(db, project_id)
        if mode not in ("baseline", "memory"):
            mode = "memory"

        if mode == "memory" and brief is None:
            brief = await self.brief_service.build_brief(db, project_id, task, file_paths)

        memory_block = brief.memory_block if (mode == "memory" and brief and brief.applied) else ""
        prompt = assemble_system_prompt(ctx, memory_block or None)
        messages: list[dict[str, str]] = [{"role": "system", "content": prompt.system}]
        for turn in (history or [])[-8:]:
            messages.append(
                {"role": "assistant" if turn["role"] == "agent" else "user", "content": turn["content"][:4000]}
            )
        messages.append({"role": "user", "content": task.strip()})

        run = TaskRun(
            project_id=project_id,
            session_id=session_id,
            comparison_id=comparison_id,
            repeat_index=repeat_index,
            mode=mode,
            task=task.strip(),
            model=getattr(self.llm, "model_large", None),
            temperature=0.0,
            brief_snapshot_json=brief.model_dump_json() if (mode == "memory" and brief) else None,
            prompt_hash=prompt.hash,
            injected_tokens=brief.injected_tokens if (mode == "memory" and brief) else 0,
            recall_ms=brief.recall_ms if (mode == "memory" and brief) else 0,
            filter_ms=brief.filter_ms if (mode == "memory" and brief) else 0,
            summary="",
        )
        llm_started = time.perf_counter()
        output = RunOutput(summary="")
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        error: dict | None = None
        try:
            result = await self.llm.complete_json(
                tier="large",
                messages=messages,
                schema=GenerationOutput,
                job="generate",
                temperature=0.0,
                max_tokens=2048,
            )
            parsed: GenerationOutput = result.parsed
            usage = result.usage
            run.model = result.model
            followed = self._map_followed(parsed.followed_record_ids, brief if mode == "memory" else None)
            output = RunOutput(
                summary=parsed.summary,
                files=[GeneratedFileOut(**f.model_dump()) for f in parsed.files[:8]],
                notes=parsed.notes[:12],
                followed_record_ids=followed,
            )
        except AppError as exc:
            error = {"code": exc.code, "message": exc.message, "details": exc.details}
            run.status = "error"
            run.error_json = json.dumps(error, default=str)
            if raise_on_error:
                raise

        run.llm_ms = int((time.perf_counter() - llm_started) * 1000)
        run.summary = output.summary
        run.output_files_json = json.dumps([f.model_dump() for f in output.files])
        run.output_notes_json = json.dumps(output.notes)
        run.followed_record_ids_json = json.dumps(output.followed_record_ids)
        run.prompt_tokens = usage.get("prompt_tokens", 0)
        run.completion_tokens = usage.get("completion_tokens", 0)
        run.latency_ms = int((time.perf_counter() - started) * 1000)
        db.add(run)
        AuditService.log(
            db,
            project_id,
            "GENERATE",
            status="error" if error else "ok",
            latency_ms=run.llm_ms,
            run_id=run.id,
            detail={"mode": mode, "model": run.model, "prompt_tokens": run.prompt_tokens, "error": error},
        )
        db.commit()
        db.refresh(run)

        return TaskRunOut(
            id=run.id,
            project_id=project_id,
            session_id=session_id,
            comparison_id=comparison_id,
            repeat_index=repeat_index,
            mode=mode,
            task=run.task,
            status=run.status or "ok",
            error=error,
            model=run.model,
            output=output,
            brief=brief if mode == "memory" else None,
            usage=usage,
            injected_tokens=run.injected_tokens or 0,
            recall_ms=run.recall_ms or 0,
            filter_ms=run.filter_ms or 0,
            llm_ms=run.llm_ms or 0,
            latency_ms=run.latency_ms,
            created_at=iso(run.created_at) or "",
        )

    @staticmethod
    def _map_followed(values: list[str], brief: BriefResult | None) -> list[str]:
        """Accept pills or IDs from the model; keep only records that were actually injected."""
        if not brief:
            return []
        allowed = {a.record.id: a.record.id for a in brief.applied}
        allowed.update({a.record.pill.upper(): a.record.id for a in brief.applied})
        mapped: list[str] = []
        for value in values or []:
            key = value.strip()
            rid = allowed.get(key) or allowed.get(key.upper())
            if rid and rid not in mapped:
                mapped.append(rid)
        return mapped

    @staticmethod
    def output_as_text(output: RunOutput) -> str:
        """The exact text Memory Check judges: summary, notes and every file."""
        parts = [output.summary or ""]
        for note in output.notes:
            parts.append(f"- {note}")
        for f in output.files:
            parts.append(f"\n// file: {f.path}\n{f.content}")
        return "\n".join(p for p in parts if p is not None).strip()

    @staticmethod
    def records_for(db: Session, ids: list[str]) -> list[MemoryRecord]:
        return [r for r in (db.get(MemoryRecord, i) for i in ids) if r]
