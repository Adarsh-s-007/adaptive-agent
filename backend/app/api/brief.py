"""POST /projects/{pid}/brief: recall preview. Owner: P5."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.gateways.project_context import resolve
from app.schemas.brief import Brief, BriefRequest
from app.services.brief_service import build_brief

router = APIRouter(tags=["brief"])


@router.post("/projects/{project_id}/brief", response_model=Brief)
async def brief(
    project_id: uuid.UUID, body: BriefRequest, db: Annotated[AsyncSession, Depends(get_db)]
):
    ctx = await resolve(db, project_id)
    return (await build_brief(db, ctx, body.task, body.file_paths)).brief
