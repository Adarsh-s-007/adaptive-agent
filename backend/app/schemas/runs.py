"""Run request/response (contract C-9). Owner: P5."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.prompts.schemas.generation import GenerationOutput
from app.schemas.brief import Brief
from app.schemas.common import RunMode


class RunRequest(BaseModel):
    task: str = Field(min_length=3, max_length=8000)
    mode: RunMode = RunMode.memory
    session_id: uuid.UUID | None = None


class RunUsage(BaseModel):
    prompt_tokens: int | None
    completion_tokens: int | None
    injected_tokens: int


class RunLatency(BaseModel):
    recall_ms: int | None
    filter_ms: int | None
    llm_ms: int | None


class RunOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    mode: RunMode
    task: str
    model: str
    status: str
    output: GenerationOutput | None
    brief: Brief | None
    usage: RunUsage
    latency: RunLatency
    error: str | None
    created_at: datetime
