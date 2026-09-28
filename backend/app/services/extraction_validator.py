"""Deterministic validator for extracted memory candidates (EX-5, C5, S1, S2)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.common import MemoryType
from app.services.project_memory_service import SECRET_PATTERN
from app.services.signals import TRANSIENT_SIGNALS

INSTRUCTION_LIKE = re.compile(
    r"(?i)\b(please\s+(?:do|answer|write|generate)|you\s+must\s+(?:respond|answer|output)|as\s+an\s+ai)\b"
)

VALID_TAXONOMY = {t.value for t in MemoryType}


@dataclass
class ValidationResult:
    valid: bool
    status: str  # pending or filtered
    reason: str | None = None
    adjusted_confidence: float = 0.8
    flagged: bool = False


class ExtractionValidator:
    """Deterministic validation pipeline for memory candidates before human review."""

    MIN_STATEMENT_LEN = 20
    MAX_STATEMENT_LEN = 400

    @classmethod
    def validate(
        cls,
        statement: str,
        memory_type: str,
        evidence_quote: str,
        transcript_texts: list[str],
        stated_by: str = "human",
        initial_confidence: float = 0.8,
    ) -> ValidationResult:
        clean_statement = statement.strip()
        clean_quote = evidence_quote.strip()

        # 1. Secret check
        if SECRET_PATTERN.search(clean_statement) or SECRET_PATTERN.search(clean_quote):
            return ValidationResult(
                valid=False,
                status="filtered",
                reason="Statement or quote appears to contain secrets or credentials.",
            )

        # 2. Taxonomy check
        if memory_type not in VALID_TAXONOMY:
            return ValidationResult(
                valid=False,
                status="filtered",
                reason=f"Unsupported memory type '{memory_type}'. Must be one of {sorted(VALID_TAXONOMY)}.",
            )

        # 3. Length check (20-400 chars)
        if len(clean_statement) < cls.MIN_STATEMENT_LEN:
            return ValidationResult(
                valid=False,
                status="filtered",
                reason=f"Statement is too short ({len(clean_statement)} chars). Minimum is {cls.MIN_STATEMENT_LEN}.",
            )
        if len(clean_statement) > cls.MAX_STATEMENT_LEN:
            return ValidationResult(
                valid=False,
                status="filtered",
                reason=f"Statement is too long ({len(clean_statement)} chars). Maximum is {cls.MAX_STATEMENT_LEN}.",
            )

        # 4. Verbatim quote presence in transcript turns (C5)
        quote_found = any(clean_quote in turn_text for turn_text in transcript_texts)
        if not quote_found:
            return ValidationResult(
                valid=False,
                status="filtered",
                reason="Evidence quote does not appear verbatim in any session turn.",
            )

        # 5. Transient state check
        if TRANSIENT_SIGNALS.search(clean_statement):
            return ValidationResult(
                valid=False,
                status="filtered",
                reason="Candidate represents a transient state or WIP item, not a durable decision.",
            )

        # 6. Instruction-like check
        flagged = bool(INSTRUCTION_LIKE.search(clean_statement))

        # 7. Agent-only confidence cap at 0.4
        conf = initial_confidence
        if stated_by == "agent":
            conf = min(conf, 0.4)

        return ValidationResult(
            valid=True,
            status="pending",
            adjusted_confidence=conf,
            flagged=flagged,
        )
