"""The only module that talks to Groq (contract C-6, blueprint section 16). Owner: P5.

All jobs use JSON output validated by a Pydantic model, with one repair retry.
Uses Groq's OpenAI-compatible HTTP API directly.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Generic, Literal, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
Tier = Literal["large", "small"]
T = TypeVar("T", bound=BaseModel)

# Per-job timeouts: 30 s for generation-sized jobs, 15 s for small classification jobs.
TIMEOUTS = {"large": 30.0, "small": 15.0}


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class LLMResult(Generic[T]):
    parsed: T
    usage: Usage
    raw: str
    model: str
    latency_ms: int


class LLMGateway:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def model_for(self, tier: Tier) -> str:
        s = get_settings()
        return s.llm_model_large if tier == "large" else s.llm_model_small

    async def complete_json(
        self,
        tier: Tier,
        messages: list[dict],
        schema: type[T],
        *,
        job: str,
        temperature: float = 0,
        max_tokens: int = 2048,
    ) -> LLMResult[T]:
        model = self.model_for(tier)
        started = time.perf_counter()
        usage = Usage()
        convo = list(messages)
        raw = ""
        for attempt in range(2):  # first try + one repair retry
            raw, call_usage = await self._call(model, tier, convo, schema, temperature, max_tokens)
            usage.prompt_tokens += call_usage.prompt_tokens
            usage.completion_tokens += call_usage.completion_tokens
            try:
                parsed = schema.model_validate_json(raw)
                return LLMResult(
                    parsed=parsed,
                    usage=usage,
                    raw=raw,
                    model=model,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            except ValidationError as exc:
                if attempt == 1:
                    break
                convo = [
                    *messages,
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": "Your JSON did not match the schema. Errors:\n"
                        + str(exc)[:1500]
                        + "\nReturn only corrected JSON.",
                    },
                ]
        raise AppError(
            ErrorCode.LLM_OUTPUT_INVALID,
            f"The model returned invalid output for {job}.",
            details={"raw": raw[:4000], "job": job},
        )

    async def _call(
        self,
        model: str,
        tier: Tier,
        messages: list[dict],
        schema: type[BaseModel],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, Usage]:
        key = get_settings().groq_api_key
        if not key:
            raise AppError(ErrorCode.LLM_UNAVAILABLE, "GROQ_API_KEY is not configured.")
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
            },
        }
        headers = {"Authorization": f"Bearer {key}"}
        client = self._client or httpx.AsyncClient()
        try:
            for attempt in range(2):  # one retry on timeout/5xx/429
                try:
                    resp = await client.post(
                        GROQ_URL, json=payload, headers=headers, timeout=TIMEOUTS[tier]
                    )
                except httpx.TimeoutException:
                    if attempt == 0:
                        continue
                    raise AppError(ErrorCode.LLM_UNAVAILABLE, "The model timed out.") from None
                if resp.status_code == 429 and attempt == 0:
                    wait = min(float(resp.headers.get("retry-after", "1") or 1), 5.0)
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code >= 500 and attempt == 0:
                    continue
                if resp.status_code >= 400:
                    raise AppError(
                        ErrorCode.LLM_UNAVAILABLE,
                        f"Groq rejected the request (HTTP {resp.status_code}).",
                    )
                body = resp.json()
                content = body["choices"][0]["message"].get("content") or ""
                u = body.get("usage") or {}
                return content, Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
            raise AppError(ErrorCode.LLM_UNAVAILABLE, "Groq is unavailable.")
        except httpx.HTTPError as exc:
            raise AppError(ErrorCode.LLM_UNAVAILABLE, "Groq is unreachable.") from exc
        finally:
            if self._client is None:
                await client.aclose()

    async def health(self) -> str:
        return "ok" if get_settings().groq_api_key else "down"


@lru_cache
def get_llm_gateway() -> LLMGateway:
    return LLMGateway()
