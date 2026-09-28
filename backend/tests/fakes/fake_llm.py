"""Scriptable fake LLM: per-job responses or callables, call history, failure modes."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.errors import AppError, AppErrorCode
from app.gateways.llm_gateway import LLMResult

T = TypeVar("T", bound=BaseModel)


class FakeLLM:
    model_large = "fake-large"
    model_small = "fake-small"

    def __init__(self, configured: bool = True) -> None:
        self.configured = configured
        self.responses_by_job: dict[str, Any] = {}
        self.fail_jobs: dict[str, str] = {}
        self.call_history: list[dict[str, Any]] = []

    def set_job_response(self, job: str, response: Any) -> None:
        self.responses_by_job[job] = response

    def fail(self, job: str, code: str = AppErrorCode.LLM_UNAVAILABLE) -> None:
        self.fail_jobs[job] = code

    async def health(self) -> dict[str, Any]:
        return {"status": "ok" if self.configured else "unconfigured"}

    async def aclose(self) -> None:
        return None

    async def complete_json(self, tier, messages, schema: type[T], *, job, temperature=0.0, max_tokens=1500) -> LLMResult:
        self.call_history.append({"job": job, "tier": tier, "messages": messages})
        if not self.configured:
            raise AppError(AppErrorCode.LLM_UNAVAILABLE, "not configured", status_code=503)
        if job in self.fail_jobs:
            raise AppError(self.fail_jobs[job], f"Simulated {job} failure", status_code=502)
        configured = self.responses_by_job.get(job)
        if isinstance(configured, Callable):
            configured = configured(messages)
        if configured is None:
            configured = {"summary": "ok"} if job == "generate" else {}
        parsed = configured if isinstance(configured, BaseModel) else schema.model_validate(configured)
        return LLMResult(
            parsed=parsed,
            usage={"prompt_tokens": sum(len(m["content"]) for m in messages) // 4, "completion_tokens": 50, "total_tokens": 0},
            raw=json.dumps(configured) if not isinstance(configured, BaseModel) else configured.model_dump_json(),
            model=self.model_large if tier == "large" else self.model_small,
            latency_ms=5,
        )

    def jobs(self) -> list[str]:
        return [c["job"] for c in self.call_history]
