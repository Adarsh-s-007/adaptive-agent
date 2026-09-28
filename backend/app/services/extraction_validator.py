"""Deterministic validator for extracted candidates — no LLM (Blueprint §5.2 step 4, §16.7)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.core.secrets import contains_pii, contains_secret
from app.core.taxonomy import is_known_type, normalize_type
from app.services.signals import TRANSIENT_SIGNALS

# Instruction-like text that could poison a prompt if it reached an agent (S1).
INSTRUCTION_LIKE = re.compile(
    r"(?i)(ignore (?:all |any )?(?:the )?(?:previous|prior|above) (?:instructions|rules)|"
    r"disregard (?:all |the )?(?:previous|above)|you must now|you are now|new instructions|"
    r"^\s*system\s*:|<\s*/?\s*(?:system|assistant|user)\s*>|\[/?INST\]|as an ai\b|"
    r"reveal (?:the |your )?(?:system )?prompt|override (?:the )?rules)"
)

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def normalize_for_match(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").translate(_QUOTES)
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip().lower()


@dataclass
class ValidationResult:
    valid: bool
    status: str  # pending · auto_rejected
    reason: str | None = None
    adjusted_confidence: float = 0.8
    flagged: bool = False
    flags: list[str] = field(default_factory=list)
    memory_type: str = "decision"
    matched_turn: int | None = None


class ExtractionValidator:
    """Rejects hallucinated evidence, secrets, transient chatter and out-of-taxonomy items."""

    MIN_STATEMENT_LEN = 20
    MAX_STATEMENT_LEN = 400
    MIN_QUOTE_LEN = 8

    @classmethod
    def validate(
        cls,
        statement: str,
        memory_type: str,
        evidence_quote: str,
        transcript_texts: list[str],
        stated_by: str = "human",
        initial_confidence: float = 0.8,
        turn_indices: list[int] | None = None,
    ) -> ValidationResult:
        statement = (statement or "").strip()
        quote = (evidence_quote or "").strip()

        def reject(reason: str) -> ValidationResult:
            return ValidationResult(False, "auto_rejected", reason, 0.0, memory_type=normalize_type(memory_type))

        if contains_secret(statement) or contains_secret(quote):
            return reject("Contains something that looks like a secret or credential.")
        if contains_pii(statement):
            return reject("Contains personal data (email address or card-like number).")
        if not is_known_type(memory_type):
            return reject(f"Type '{memory_type}' is outside the eight-type taxonomy.")
        if len(statement) < cls.MIN_STATEMENT_LEN:
            return reject(f"Statement is too short ({len(statement)} chars; minimum {cls.MIN_STATEMENT_LEN}).")
        if len(statement) > cls.MAX_STATEMENT_LEN:
            return reject(f"Statement is too long ({len(statement)} chars; maximum {cls.MAX_STATEMENT_LEN}).")
        if len(quote) < cls.MIN_QUOTE_LEN:
            return reject("Evidence quote is missing or too short to verify.")

        needle = normalize_for_match(quote)
        matched_turn: int | None = None
        for position, text in enumerate(transcript_texts):
            if needle in normalize_for_match(text):
                matched_turn = turn_indices[position] if turn_indices else position + 1
                break
        if matched_turn is None:
            return reject("Evidence quote is not a verbatim substring of the transcript.")

        if TRANSIENT_SIGNALS.search(statement):
            return reject("Describes transient state (branch, local machine, current build), not a durable rule.")

        flags: list[str] = []
        if INSTRUCTION_LIKE.search(statement) or INSTRUCTION_LIKE.search(quote):
            flags.append("instruction_like")

        confidence = max(0.0, min(1.0, initial_confidence))
        normalized_type = normalize_type(memory_type)
        if stated_by == "agent" and normalized_type in ("decision", "security_constraint", "preference", "convention"):
            confidence = min(confidence, 0.4)
            flags.append("agent_proposed")

        return ValidationResult(
            valid=True,
            status="pending",
            adjusted_confidence=confidence,
            flagged="instruction_like" in flags,
            flags=flags,
            memory_type=normalized_type,
            matched_turn=matched_turn,
        )
