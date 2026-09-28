"""LLM Gateway with JSON-schema output, repair retry, and token usage capture (GN-1, C-6)."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from app.config import get_settings
from app.core.errors import AppError, AppErrorCode
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResult:
    parsed: Any
    usage: dict[str, int]
    raw: str
    model: str
    latency_ms: int


class LLMGateway:
    """The authoritative interface for all LLM calls (generation, judge, applicability, extract)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.model_large = os.environ.get("LLM_MODEL_LARGE", "openai/gpt-oss-120b")
        self.model_small = os.environ.get("LLM_MODEL_SMALL", "openai/gpt-oss-20b")
        self.api_key = self.settings.groq_api_key or os.environ.get("GROQ_API_KEY", "")

    def get_model(self, tier: str) -> str:
        if tier == "large":
            return self.model_large or "llama-3.3-70b-versatile"
        return self.model_small or "llama-3.3-70b-versatile"

    async def health(self) -> dict[str, Any]:
        if not self.api_key:
            return {"status": "unconfigured", "configured": False}
        return {"status": "ok", "configured": True, "large": self.model_large, "small": self.model_small}

    async def complete_json(
        self,
        tier: str,
        messages: list[dict[str, str]],
        schema: type[T],
        *,
        job: str,
        temperature: float = 0.0,
        max_tokens: int = 1500,
    ) -> LLMResult:
        """Call LLM with JSON schema output, Pydantic validation, and repair retry."""
        if not self.api_key:
            raise AppError(
                code=AppErrorCode.LLM_UNAVAILABLE,
                message="LLM API key not configured.",
                status_code=503,
            )

        model = self.get_model(tier)
        timeout = 30.0 if tier == "large" else 15.0
        start_time = time.perf_counter()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        schema_json = json.dumps(schema.model_json_schema())
        augmented_messages = list(messages)
        # Ensure schema constraint in prompt
        augmented_messages[0]["content"] += f"\n\nYou MUST respond with valid JSON matching this schema:\n{schema_json}"

        payload: dict[str, Any] = {
            "model": model,
            "messages": augmented_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        # Attempt 1
        raw_text = ""
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    
                    if resp.status_code == 429:
                        retry_after = min(int(resp.headers.get("retry-after", "2")), 5)
                        time.sleep(retry_after)
                        continue

                    if resp.status_code >= 400:
                        raise AppError(
                            code=AppErrorCode.LLM_UNAVAILABLE,
                            message=f"LLM provider error: HTTP {resp.status_code}",
                            status_code=503,
                        )

                    data = resp.json()
                    choices = data.get("choices", [])
                    if not choices:
                        raise ValueError("Empty completion choices")

                    raw_text = choices[0].get("message", {}).get("content", "").strip()
                    usage_data = data.get("usage", {})
                    usage = {
                        "prompt_tokens": usage_data.get("prompt_tokens", 0),
                        "completion_tokens": usage_data.get("completion_tokens", 0),
                        "total_tokens": usage_data.get("total_tokens", 0),
                    }
                    break
            except Exception as e:
                if attempt == 1:
                    raise AppError(
                        code=AppErrorCode.LLM_UNAVAILABLE,
                        message=f"LLM completion failed: {e!s}",
                        status_code=503,
                    )
                time.sleep(1.0)

        # Parse & validate JSON
        try:
            parsed_data = json.loads(raw_text)
            parsed_obj = schema.model_validate(parsed_data)
        except Exception as exc:
            # One repair attempt
            repair_messages = [
                {"role": "system", "content": f"Fix the following malformed JSON to strictly match the schema:\n{schema_json}"},
                {"role": "user", "content": f"Malformed output:\n{raw_text}\nError:\n{exc!s}"},
            ]
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    repair_resp = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers=headers,
                        json={
                            "model": self.model_small,
                            "messages": repair_messages,
                            "temperature": 0.0,
                            "response_format": {"type": "json_object"},
                        },
                    )
                    repair_raw = repair_resp.json()["choices"][0]["message"]["content"]
                    parsed_obj = schema.model_validate(json.loads(repair_raw))
            except Exception:
                raise AppError(
                    code=AppErrorCode.LLM_OUTPUT_INVALID,
                    message=f"LLM produced invalid JSON for job '{job}'.",
                    status_code=502,
                    details={"raw": raw_text[:500]},
                )

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return LLMResult(
            parsed=parsed_obj,
            usage=usage,
            raw=raw_text,
            model=model,
            latency_ms=latency_ms,
        )
