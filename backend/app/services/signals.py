"""Transcript preparation (truncation, redaction, windows) and signal hints (Blueprint §5.1-5.2)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.secrets import SECRET_PATTERN
from app.core.tokens import count_tokens
from app.services.transcript_parser import ParsedTurn

# Signals that a turn holds something worth remembering. Hints only: the LLM decides.
SIGNAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "correction": re.compile(r"(?i)^\s*(no[,.! —-]|nope|don't|do not|stop|wrong|that's not|actually,? we)"),
    "decision": re.compile(
        r"(?i)\b(we decided|we've decided|decided to|from now on|going forward|always|never|must|must not|"
        r"is forbidden|not allowed|mandatory|our rule|team rule|the rule is|standard is|convention is)\b"
    ),
    "rationale": re.compile(r"(?i)\b(because|so that|the reason|due to|otherwise|audit(?:ors)?|compliance)\b"),
    "incident": re.compile(
        r"(?i)\b(root cause|post-?mortem|incident|outage|504|500s|timed? ?out|exhaust(?:ed|ion)|traceback|stack trace)\b"
    ),
    "failed_approach": re.compile(
        r"(?i)\b(we tried|tried .{0,40} and|reverted|rolled back|didn't work|did not work|lost data|vanished|abandoned)\b"
    ),
    "obsolete": re.compile(r"(?i)\b(obsolete|no longer|replaces?|superseded?|instead of|migrated (?:from|to))\b"),
    "deployment": re.compile(r"(?i)\b(only ci|in ci|migrat(?:e|ion)s?|deploy(?:ment)?|vercel|render|docker|env var)\b"),
}

# Backwards-compatible single patterns.
DECISION_SIGNALS = SIGNAL_PATTERNS["decision"]
TRANSIENT_SIGNALS = re.compile(
    r"(?i)\b(currently (?:working on|failing|broken)|in progress|will fix later|wip|i'?m on branch|"
    r"on my machine|my local|build (?:is )?(?:currently )?failing|today i|this morning|right now|todo:|"
    r"status update|investigating|local build|this laptop|i'?m on node|heading out|for lunch)\b"
)


@dataclass
class TranscriptWindow:
    turns: list[ParsedTurn]
    start_index: int
    end_index: int


class TranscriptPreparer:
    """Prepares turns for extraction: truncate tool output, redact secrets, flag hints."""

    MAX_TOOL_CHARS = 1500
    WINDOW_TOKENS = 8000
    SINGLE_PASS_TOKENS = 12000

    @classmethod
    def scrub_secrets(cls, text: str) -> str:
        return SECRET_PATTERN.sub("[REDACTED_SECRET]", text)

    @classmethod
    def prepare_turns(cls, turns: list[ParsedTurn]) -> list[ParsedTurn]:
        prepared: list[ParsedTurn] = []
        for t in turns:
            content = t.content
            if t.role == "tool" and len(content) > cls.MAX_TOOL_CHARS:
                content = content[: cls.MAX_TOOL_CHARS] + "\n… [tool output truncated]"
            prepared.append(
                ParsedTurn(
                    role=t.role,
                    content=cls.scrub_secrets(content),
                    turn_index=t.turn_index,
                    speaker=t.speaker,
                )
            )
        return prepared

    @classmethod
    def find_signal_hints(cls, text: str) -> list[str]:
        return [name for name, pattern in SIGNAL_PATTERNS.items() if pattern.search(text)]

    @classmethod
    def hint_turns(cls, turns: list[ParsedTurn]) -> dict[int, list[str]]:
        hints: dict[int, list[str]] = {}
        for t in turns:
            if t.role == "tool":
                continue
            found = cls.find_signal_hints(t.content)
            if found:
                hints[t.turn_index] = found
        return hints

    @classmethod
    def windows(cls, turns: list[ParsedTurn]) -> list[TranscriptWindow]:
        """Split long transcripts into overlapping ~8k-token windows (§5.2 step 1)."""
        total = sum(count_tokens(t.content) for t in turns)
        if total <= cls.SINGLE_PASS_TOKENS or not turns:
            return [TranscriptWindow(turns, turns[0].turn_index if turns else 0, turns[-1].turn_index if turns else 0)]
        windows: list[TranscriptWindow] = []
        start = 0
        while start < len(turns):
            size = 0
            end = start
            while end < len(turns) and size < cls.WINDOW_TOKENS:
                size += count_tokens(turns[end].content)
                end += 1
            chunk = turns[start:end]
            windows.append(TranscriptWindow(chunk, chunk[0].turn_index, chunk[-1].turn_index))
            if end >= len(turns):
                break
            start = max(start + 1, end - 3)  # three-turn overlap
        return windows
