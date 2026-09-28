"""POST /projects/{pid}/runs and GET /projects/{pid}/runs/{run_id}. Owner: P5."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.db.models import TaskRun
from app.db.session import get_db
from app.schemas.brief import Brief
from app.schemas.runs import RunLatency, RunOut, RunRequest, RunUsage
from app.services import generation_service

router = APIRouter(prefix="/projects/{project_id}/runs", tags=["runs"])
DB = Annotated[AsyncSession, Depends(get_db)]


def to_out(run: TaskRun, brief: Brief | None = None) -> RunOut:
    if brief is None and run.mode == "memory" and run.recall_query is not None:
        brief = Brief(
            status="ok" if run.applied else "empty",
            query=run.recall_query,
            recalled=run.recalled,
            applied=run.applied,
            filtered=run.filtered,
            recall_ms=run.recall_ms,
            filter_ms=run.filter_ms,
            injected_tokens=run.injected_tokens,
        )
    return RunOut(
        id=run.id,
        project_id=run.project_id,
        mode=run.mode,
        task=run.task,
        model=run.model,
        status=run.status,
        output=run.output,
        brief=brief,
        usage=RunUsage(
            prompt_tokens=run.prompt_tokens,
            completion_tokens=run.completion_tokens,
            injected_tokens=run.injected_tokens,
        ),
        latency=RunLatency(recall_ms=run.recall_ms, filter_ms=run.filter_ms, llm_ms=run.llm_ms),
        error=run.error,
        created_at=run.created_at,
    )


@router.post("", response_model=RunOut, status_code=201)
async def create_run(project_id: uuid.UUID, body: RunRequest, db: DB):
    run, brief = await generation_service.run(
        db, project_id, body.task, body.mode, session_id=body.session_id
    )
    return to_out(run, brief)


@router.get("/{run_id}", response_model=RunOut)
async def get_run(project_id: uuid.UUID, run_id: uuid.UUID, db: DB):
    run = await db.get(TaskRun, run_id)
    if run is None or run.project_id != project_id:
        raise AppError(ErrorCode.NOT_FOUND, "Run not found.")
    return to_out(run)
