"""Runs in baseline or memory mode (blueprint 4.4, 11). Owner: P5.

Public: run(db, project_id, task, mode, session_id=None) -> TaskRun  (used by P6 Compare)
Baseline runs make zero Hindsight calls (test M1).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.db.models import Project, TaskRun
from app.gateways.hindsight_gateway import HindsightGateway
from app.gateways.llm_gateway import LLMGateway, get_llm_gateway
from app.gateways.project_context import resolve
from app.prompts.schemas.generation import GenerationOutput
from app.schemas.brief import Brief, BriefStatus
from app.services.brief_service import build_brief
from app.services.prompt_assembler import build_messages


async def run(
    db: AsyncSession,
    project_id: uuid.UUID,
    task: str,
    mode: str,
    *,
    session_id: uuid.UUID | None = None,
    comparison_id: uuid.UUID | None = None,
    hindsight: HindsightGateway | None = None,
    llm: LLMGateway | None = None,
) -> tuple[TaskRun, Brief | None]:
    llm = llm or get_llm_gateway()
    project = await db.get(Project, project_id)
    if project is None:
        raise AppError(ErrorCode.NOT_FOUND, "Project not found.")

    brief: Brief | None = None
    records = None
    if mode == "memory":
        ctx = await resolve(db, project_id)
        result = await build_brief(db, ctx, task, hindsight=hindsight, llm=llm)
        brief = result.brief
        if brief.status == BriefStatus.memory_unavailable:
            raise AppError(
                ErrorCode.HINDSIGHT_UNAVAILABLE,
                "Project memory is unavailable, so a memory-aware run cannot start. "
                "Baseline runs still work.",
            )
        records = result.applied_records

    messages, _ = build_messages(project, task, records)
    run_row = TaskRun(
        project_id=project_id,
        session_id=session_id,
        comparison_id=comparison_id,
        mode=mode,
        task=task,
        model=llm.model_for("large"),
        temperature=0,
        recall_query=brief.query if brief else None,
        recalled=[i.model_dump(mode="json") for i in brief.recalled] if brief else [],
        applied=[i.model_dump(mode="json") for i in brief.applied] if brief else [],
        filtered=[i.model_dump(mode="json") for i in brief.filtered] if brief else [],
        injected_tokens=brief.injected_tokens if brief else 0,
        recall_ms=brief.recall_ms if brief else None,
        filter_ms=brief.filter_ms if brief else None,
        status="running",
    )
    db.add(run_row)
    await db.commit()

    try:
        result = await llm.complete_json("large", messages, GenerationOutput, job="generate")
    except AppError as exc:
        run_row.status = "error"
        run_row.error = f"{exc.code}: {exc.message}"
        await db.commit()
        raise
    output = result.parsed
    allowed = {str(r.id) for r in records or []}
    output.followed_record_ids = [i for i in output.followed_record_ids if i in allowed]
    run_row.output = output.model_dump()
    run_row.followed_record_ids = output.followed_record_ids
    run_row.prompt_tokens = result.usage.prompt_tokens
    run_row.completion_tokens = result.usage.completion_tokens
    run_row.llm_ms = result.latency_ms
    run_row.status = "done"
    await db.commit()
    return run_row, brief
