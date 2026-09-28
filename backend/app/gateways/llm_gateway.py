"""LLMGateway: the only module that talks to the LLM provider (Blueprint §16).

- Groq (or any OpenAI-compatible endpoint) with JSON-schema structured output.
- Pydantic validation of every output, one repair retry that sends the validation
  error back, then LLM_OUTPUT_INVALID with the raw text preserved.
- 429: honour retry-after up to 5 s, one retry. Timeout/5xx: one retry.
- Usage and latency captured for every call.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.core.errors import AppError, AppErrorCode
from app.core.logging import get_logger, redact

log = get_logger("llm")
T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResult:
    parsed: Any
    usage: dict[str, int]
    raw: str
    model: str
    latency_ms: int


def _strip_fences(text: str) -> str:
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if match:
        return match.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start > 0 and end > start:
        return text[start : end + 1]
    return text


class LLMGateway:
    """The authoritative interface for generation, judging, extraction and classification."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.model_large = self.settings.llm_model_large
        self.model_small = self.settings.llm_model_small
        self.api_key = self.settings.groq_api_key or ""
        self._schema_mode_supported: dict[str, bool] = {}
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None
        self._health_cache: tuple[float, dict[str, Any]] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def get_model(self, tier: str) -> str:
        return self.model_large if tier == "large" else self.model_small

    def _get_client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        if self._client is None or self._client_loop is not loop or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.settings.llm_base_url.rstrip("/"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(30.0, connect=5.0),
            )
            self._client_loop = loop
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            try:
                await self._client.aclose()
            except RuntimeError:
                pass
        self._client = None

    async def health(self) -> dict[str, Any]:
        if not self.configured:
            return {"status": "unconfigured", "message": "GROQ_API_KEY is not set."}
        now = time.monotonic()
        if self._health_cache and now - self._health_cache[0] < 30:
            return self._health_cache[1]
        try:
            started = time.perf_counter()
            response = await self._get_client().get("/models", timeout=4.0)
            latency = int((time.perf_counter() - started) * 1000)
            if response.status_code < 400:
                result = {
                    "status": "ok",
                    "latency_ms": latency,
                    "large": self.model_large,
                    "small": self.model_small,
                }
            elif response.status_code in (401, 403):
                result = {"status": "down", "message": "The LLM API key was rejected."}
            else:
                result = {"status": "degraded", "message": f"HTTP {response.status_code}"}
        except httpx.HTTPError as exc:
            result = {"status": "down", "message": type(exc).__name__}
        self._health_cache = (now, result)
        return result

    async def _post(self, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        """One chat completion with the §16.6 retry policy."""
        client = self._get_client()
        for attempt in (1, 2):
            try:
                response = await client.post("/chat/completions", json=payload, timeout=timeout)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == 1:
                    await asyncio.sleep(0.5)
                    continue
                raise AppError(
                    AppErrorCode.LLM_UNAVAILABLE,
                    f"LLM call failed: {type(exc).__name__}.",
                    status_code=503,
                ) from exc
            if response.status_code == 429 and attempt == 1:
                retry_after = response.headers.get("retry-after", "2")
                try:
                    delay = min(float(retry_after), 5.0)
                except ValueError:
                    delay = 2.0
                await asyncio.sleep(delay)
                continue
            if response.status_code >= 500 and attempt == 1:
                await asyncio.sleep(0.5)
                continue
            if response.status_code >= 400:
                body = redact(response.text[:400])
                raise AppError(
                    AppErrorCode.LLM_UNAVAILABLE,
                    f"LLM provider returned HTTP {response.status_code}.",
                    status_code=503 if response.status_code != 400 else 502,
                    details={"provider_status": response.status_code, "body": body},
                )
            return response.json()
        raise AppError(AppErrorCode.LLM_UNAVAILABLE, "LLM call failed.", status_code=503)

    def _payload(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
        job: str,
        temperature: float,
        max_tokens: int,
        tier: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self._schema_mode_supported.get(model, True):
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": re.sub(r"[^a-zA-Z0-9_]", "_", job)[:60] or "output",
                    "schema": schema.model_json_schema(),
                    "strict": False,
                },
            }
        else:
            payload["response_format"] = {"type": "json_object"}
        if "gpt-oss" in model:
            payload["reasoning_effort"] = "medium" if tier == "large" else "low"
        return payload

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
        """Run one structured-output job and return a validated Pydantic object."""
        if not self.configured:
            raise AppError(
                AppErrorCode.LLM_UNAVAILABLE,
                "No LLM is configured. Set GROQ_API_KEY on the server.",
                status_code=503,
            )
        model = self.get_model(tier)
        timeout = 30.0 if tier == "large" else 15.0
        started = time.perf_counter()
        schema_json = json.dumps(schema.model_json_schema())
        messages = [dict(m) for m in messages]
        messages[0]["content"] = (
            messages[0]["content"]
            + "\n\nRespond with a single JSON object that matches this JSON Schema exactly. "
            + "No prose, no markdown fences.\n"
            + schema_json
        )

        payload = self._payload(model, messages, schema, job, temperature, max_tokens, tier)
        try:
            data = await self._post(payload, timeout)
        except AppError as exc:
            status = (exc.details or {}).get("provider_status")
            if status == 400 and payload["response_format"]["type"] == "json_schema":
                # Some models reject json_schema/reasoning params; fall back once.
                self._schema_mode_supported[model] = False
                payload["response_format"] = {"type": "json_object"}
                payload.pop("reasoning_effort", None)
                data = await self._post(payload, timeout)
            else:
                raise

        usage = self._usage(data)
        raw = self._content(data)
        parsed, error = self._validate(raw, schema)
        if parsed is None:
            repair_messages = messages + [
                {"role": "assistant", "content": raw[:6000]},
                {
                    "role": "user",
                    "content": (
                        "That output failed validation:\n"
                        f"{error}\nReturn the corrected JSON object only."
                    ),
                },
            ]
            repair_payload = dict(payload, messages=repair_messages)
            try:
                repair_data = await self._post(repair_payload, timeout)
                repair_raw = self._content(repair_data)
                for key, value in self._usage(repair_data).items():
                    usage[key] = usage.get(key, 0) + value
                parsed, error = self._validate(repair_raw, schema)
                if parsed is not None:
                    raw = repair_raw
            except AppError:
                parsed = None
            if parsed is None:
                log.warning("LLM output invalid for job %s", job)
                raise AppError(
                    AppErrorCode.LLM_OUTPUT_INVALID,
                    f"The model returned invalid output for '{job}' after one repair attempt.",
                    status_code=502,
                    details={"raw": raw[:4000], "validation_error": str(error)[:1000]},
                )

        return LLMResult(
            parsed=parsed,
            usage=usage,
            raw=raw,
            model=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    def _content(data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            return ""
        return (choices[0].get("message") or {}).get("content") or ""

    @staticmethod
    def _usage(data: dict[str, Any]) -> dict[str, int]:
        usage = data.get("usage") or {}
        return {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        }

    @staticmethod
    def _validate(raw: str, schema: type[T]) -> tuple[T | None, str | None]:
        try:
            return schema.model_validate(json.loads(_strip_fences(raw))), None
        except (ValueError, ValidationError) as exc:
            return None, str(exc)


_gateway: LLMGateway | None = None


def get_llm_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
