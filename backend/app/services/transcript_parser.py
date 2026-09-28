"""Transcript import parser supporting Markdown, JSONL, and plain text (EX-2)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from app.core.errors import AppError, AppErrorCode

SpeakerRole = Literal["human", "agent", "tool"]


@dataclass
class ParsedTurn:
    role: SpeakerRole
    content: str
    turn_index: int


class TranscriptParser:
    """Parses transcripts in Markdown, JSONL, or plain text up to 200,000 characters."""

    MAX_CHARS = 200_000

    @classmethod
    def parse(cls, raw: str, format_hint: str = "markdown") -> list[ParsedTurn]:
        if len(raw) > cls.MAX_CHARS:
            raise AppError(
                code=AppErrorCode.VALIDATION_FAILED,
                message=f"Transcript exceeds maximum size of {cls.MAX_CHARS} characters.",
                status_code=400,
            )

        raw = raw.strip()
        if not raw:
            return []

        # Auto-detect JSONL
        if format_hint == "jsonl" or raw.startswith("{"):
            return cls._parse_jsonl(raw)
        
        return cls._parse_markdown(raw)

    @classmethod
    def _parse_jsonl(cls, raw: str) -> list[ParsedTurn]:
        turns: list[ParsedTurn] = []
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        for idx, line in enumerate(lines, start=1):
            try:
                data = json.loads(line)
            except Exception:
                continue
            
            raw_role = str(data.get("role") or data.get("speaker") or "human").lower()
            role: SpeakerRole = "agent" if "agent" in raw_role or "assistant" in raw_role else (
                "tool" if "tool" in raw_role or "system" in raw_role else "human"
            )
            content = str(data.get("content") or data.get("text") or "")
            if content.strip():
                turns.append(ParsedTurn(role=role, content=content.strip(), turn_index=idx))
        return turns

    @classmethod
    def _parse_markdown(cls, raw: str) -> list[ParsedTurn]:
        turns: list[ParsedTurn] = []
        # Pattern matching: Human (Priya): ..., Agent: ..., Tool: ...
        pattern = re.compile(
            r"(?:\n|^)(?:###?\s*)?(Human(?:\s*\([^)]*\))?|Agent|Assistant|User|Tool):\s*",
            re.IGNORECASE,
        )
        splits = pattern.split(raw)
        
        # If no explicit markers found, treat as single human turn
        if len(splits) <= 1:
            return [ParsedTurn(role="human", content=raw, turn_index=1)]

        idx = 1
        i = 1
        while i < len(splits) - 1:
            speaker_tag = splits[i].lower()
            content = splits[i + 1].strip()
            role: SpeakerRole = "agent" if "agent" in speaker_tag or "assistant" in speaker_tag else (
                "tool" if "tool" in speaker_tag else "human"
            )
            if content:
                turns.append(ParsedTurn(role=role, content=content, turn_index=idx))
                idx += 1
            i += 2

        return turns
