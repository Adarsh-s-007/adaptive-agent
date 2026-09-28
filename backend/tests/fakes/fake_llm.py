"""Scriptable in-memory fake LLM for deterministic tests (GN-5)."""

from __future__ import annotations

import json
from typing import Any, Type, TypeVar
from pydantic import BaseModel

from app.core.errors import AppError, AppErrorCode
from app.gateways.llm_gateway import LLMResult

T = TypeVar("T", bound=BaseModel)


class FakeLLM:
    """Scriptable mock LLM for testing P4, P5, and P6 pipelines."""

    def __init__(self) -> None:
        self.responses_by_job: dict[str, Any] = {}
        self.invalid_json_mode: bool = False
        self.rate_limit_mode: bool = False
        self.call_history: list[dict[str, Any]] = []

    def set_job_response(self, job: str, response: Any) -> None:
        self.responses_by_job[job] = response

    async def complete_json(
        self,
        tier: str,
        messages: list[dict[str, str]],
        schema: Type[T],
        *,
        job: str,
        temperature: float = 0.0,
        max_tokens: int = 1500,
    ) -> LLMResult:
        self.call_history.append({"job": job, "tier": tier, "messages": messages})

        if self.rate_limit_mode:
            raise AppError(
                code=AppErrorCode.LLM_UNAVAILABLE,
                message="Simulated 429 rate limit",
                status_code=429,
            )

        if self.invalid_json_mode:
            raise AppError(
                code=AppErrorCode.LLM_OUTPUT_INVALID,
                message="Simulated invalid JSON output",
                status_code=502,
            )

        configured = self.responses_by_job.get(job)
        if configured is not None:
            if isinstance(configured, BaseModel):
                parsed = configured
                raw = configured.model_dump_json()
            elif isinstance(configured, dict):
                parsed = schema.model_validate(configured)
                raw = json.dumps(configured)
            else:
                raw = str(configured)
                parsed = schema.model_validate(json.loads(raw))
        else:
            # Default empty / valid instance if possible
            try:
                parsed = schema.model_validate({})
                raw = "{}"
            except Exception:
                # Return dummy payload
                raw = '{"status": "ok"}'
                parsed = schema.model_validate_json(raw)

        return LLMResult(
            parsed=parsed,
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            raw=raw,
            model="fake-llm-model",
            latency_ms=10,
        )
