"""Scriptable LLM gateway fake for unit tests. Owner: P5.

    llm = FakeLLM({"applicability": lambda messages, schema: {...}})
Handlers return a dict (validated into the schema) or raise AppError.
"""

from __future__ import annotations

from collections.abc import Callable

from app.gateways.llm_gateway import LLMResult, Usage


class FakeLLM:
    def __init__(self, handlers: dict[str, Callable] | None = None) -> None:
        self.handlers = handlers or {}
        self.calls: list[tuple[str, list[dict]]] = []

    def model_for(self, tier: str) -> str:
        return f"fake-{tier}"

    async def complete_json(self, tier, messages, schema, *, job, temperature=0, max_tokens=2048):
        self.calls.append((job, messages))
        handler = self.handlers.get(job)
        if handler is None:
            raise AssertionError(f"FakeLLM has no handler for job {job!r}")
        data = handler(messages, schema)
        return LLMResult(
            parsed=schema.model_validate(data),
            usage=Usage(prompt_tokens=100, completion_tokens=50),
            raw=str(data),
            model=self.model_for(tier),
            latency_ms=1,
        )

    async def health(self) -> str:
        return "ok"
