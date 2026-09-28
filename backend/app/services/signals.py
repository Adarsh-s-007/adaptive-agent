"""Transcript preparation, tool truncation, secret scrubbing, and signal hints (EX-3)."""

from __future__ import annotations

import re

from app.services.project_memory_service import SECRET_PATTERN
from app.services.transcript_parser import ParsedTurn

# Signals indicating durable engineering decisions
DECISION_SIGNALS = re.compile(
    r"(?i)\b(we decided|agreed to|must use|never use|forbidden|instead of|migrated to|rule:|convention:|standard:)\b"
)

TRANSIENT_SIGNALS = re.compile(
    r"(?i)\b(currently working on|in progress|will fix later|wip|investigating|trying out|status update|todo:)\b"
)


class TranscriptPreparer:
    """Prepares and scrubs transcript turns for memory candidate extraction."""

    MAX_TOOL_CHARS = 1500

    @classmethod
    def scrub_secrets(cls, text: str) -> str:
        """Replace secrets and credentials with redacted tokens."""
        return SECRET_PATTERN.sub("[REDACTED_CREDENTIAL]", text)

    @classmethod
    def prepare_turns(cls, turns: list[ParsedTurn]) -> list[ParsedTurn]:
        """Truncate excessive tool outputs and scrub sensitive data."""
        prepared: list[ParsedTurn] = []
        for t in turns:
            content = t.content
            if t.role == "tool" and len(content) > cls.MAX_TOOL_CHARS:
                content = content[:cls.MAX_TOOL_CHARS] + "\n... [Tool output truncated]"

            content = cls.scrub_secrets(content)
            prepared.append(ParsedTurn(role=t.role, content=content, turn_index=t.turn_index))
        return prepared

    @classmethod
    def find_signal_hints(cls, text: str) -> list[str]:
        """Find decision signal matches in text."""
        return DECISION_SIGNALS.findall(text)
