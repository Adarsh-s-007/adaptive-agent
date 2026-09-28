"""Transcript import parser: Markdown/plain speaker transcripts and JSONL (Blueprint §13.3)."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from app.core.errors import AppError, AppErrorCode

SpeakerRole = Literal["human", "agent", "tool"]

AGENT_WORDS = {
    "agent", "assistant", "ai", "claude", "claude code", "copilot", "codex", "cursor",
    "gpt", "bot", "model", "antigravity", "opencode", "gemini", "coding agent",
}
TOOL_WORDS = {"tool", "tool output", "system", "output", "terminal", "shell", "bash", "console"}
HUMAN_WORDS = {"human", "user", "developer", "dev", "me", "you", "engineer", "lead", "tech lead"}
NOT_SPEAKERS = {
    "note", "rule", "error", "warning", "example", "step", "todo", "summary", "input",
    "result", "rationale", "status", "decided", "applies to", "task", "file", "files",
    "reason", "fix", "cause", "symptom", "answer", "question", "context", "update", "tip",
}

_LABEL = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?(?:[-*>][ \t]+)?\**[ \t]*"
    r"(?P<label>[A-Za-z][A-Za-z0-9 ._'-]{0,40}?)"
    r"(?:[ \t]*\((?P<paren>[^)\n]{0,60})\))?"
    r"[ \t]*\**[ \t]*:[ \t]*\**[ \t]*(?P<rest>.*)$"
)


@dataclass
class ParsedTurn:
    role: SpeakerRole
    content: str
    turn_index: int
    speaker: str | None = None


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Split an optional `---`-delimited key: value header from a transcript."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}, text
    parts = stripped.split("\n")
    meta: dict[str, str] = {}
    for i, line in enumerate(parts[1:], start=1):
        if line.strip() == "---":
            return meta, "\n".join(parts[i + 1 :])
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip().lower()] = value.strip()
    return {}, text


def _role_for(label: str, paren: str | None) -> SpeakerRole | None:
    words = {label.strip().lower()}
    if paren:
        words.add(paren.strip().lower())
    if words & TOOL_WORDS:
        return "tool"
    if words & AGENT_WORDS or any(w.split()[0] in AGENT_WORDS for w in words if w):
        return "agent"
    if words & HUMAN_WORDS:
        return "human"
    return None


class TranscriptParser:
    """Parses Markdown, JSONL (incl. Claude Code / OpenAI chat exports) and plain text."""

    MAX_CHARS = 200_000

    @classmethod
    def parse(cls, raw: str, format_hint: str = "markdown") -> list[ParsedTurn]:
        if len(raw) > cls.MAX_CHARS:
            raise AppError(
                code=AppErrorCode.VALIDATION_FAILED,
                message=f"Transcript exceeds the maximum of {cls.MAX_CHARS:,} characters.",
                status_code=413,
            )
        raw = raw.replace("\r\n", "\n").strip()
        _, raw = split_front_matter(raw)
        raw = raw.strip()
        if not raw:
            return []
        if format_hint == "jsonl" or (raw.startswith("{") and "\n{" in raw) or raw.startswith("[{"):
            turns = cls._parse_jsonl(raw)
            if turns:
                return turns
        return cls._parse_markdown(raw)

    # ---------------------------------------------------------------- JSONL
    @staticmethod
    def _flatten_content(content) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    if block.get("type") in ("text", "input_text", "output_text"):
                        parts.append(str(block.get("text", "")))
                    elif block.get("type") == "tool_result":
                        parts.append(TranscriptParser._flatten_content(block.get("content")))
                    elif block.get("type") == "tool_use":
                        parts.append(f"[tool call {block.get('name', '')}] {json.dumps(block.get('input', {}))[:400]}")
            return "\n".join(p for p in parts if p)
        if isinstance(content, dict):
            return str(content.get("text") or content.get("content") or "")
        return ""

    @classmethod
    def _parse_jsonl(cls, raw: str) -> list[ParsedTurn]:
        rows: list[dict] = []
        if raw.startswith("["):
            try:
                data = json.loads(raw)
                rows = [r for r in data if isinstance(r, dict)]
            except ValueError:
                rows = []
        else:
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
        turns: list[ParsedTurn] = []
        for row in rows:
            message = row.get("message") if isinstance(row.get("message"), dict) else row
            raw_role = str(
                message.get("role") or row.get("role") or row.get("type") or row.get("speaker") or "user"
            ).lower()
            speaker = row.get("speaker") or row.get("name")
            content = cls._flatten_content(message.get("content", row.get("text", "")))
            if not content.strip():
                continue
            if raw_role in ("tool", "function", "system") or "tool" in raw_role:
                role: SpeakerRole = "tool"
            elif raw_role in ("assistant", "agent", "model", "ai"):
                role = "agent"
            else:
                role = "human"
            turns.append(
                ParsedTurn(role=role, content=content.strip(), turn_index=len(turns) + 1, speaker=speaker)
            )
        return turns

    # ------------------------------------------------------------- Markdown
    @classmethod
    def _parse_markdown(cls, raw: str) -> list[ParsedTurn]:
        lines = raw.split("\n")
        matches: list[tuple[int, str, str | None, str]] = []
        in_fence = False
        for i, line in enumerate(lines):
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            m = _LABEL.match(line)
            if m:
                matches.append((i, m.group("label").strip(), m.group("paren"), m.group("rest")))

        label_counts = Counter(label.lower() for _, label, _, _ in matches)
        speakers: list[tuple[int, SpeakerRole, str, str]] = []
        for i, label, paren, rest in matches:
            low = label.lower()
            if low in NOT_SPEAKERS:
                continue
            role = _role_for(label, paren)
            if role is None:
                # Treat a repeated, name-like label ("Priya:") as a human speaker.
                if label_counts[low] >= 2 and len(label.split()) <= 3 and label[:1].isupper():
                    role = "human"
                else:
                    continue
            speaker = paren.strip() if paren and role == "human" else label
            speakers.append((i, role, speaker, rest))

        if not speakers:
            return [ParsedTurn(role="human", content=raw, turn_index=1)]

        turns: list[ParsedTurn] = []
        preamble = "\n".join(lines[: speakers[0][0]]).strip()
        for n, (line_no, role, speaker, rest) in enumerate(speakers):
            end = speakers[n + 1][0] if n + 1 < len(speakers) else len(lines)
            body = "\n".join([rest, *lines[line_no + 1 : end]]).strip()
            if n == 0 and preamble and not preamble.startswith("#"):
                body = f"{preamble}\n{body}".strip()
            if body:
                turns.append(ParsedTurn(role=role, content=body, turn_index=len(turns) + 1, speaker=speaker))
        return turns
