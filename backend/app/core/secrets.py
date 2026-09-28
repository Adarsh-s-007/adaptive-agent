"""Secret and PII detection shared by transcript preparation and the extraction validator."""

from __future__ import annotations

import re

SECRET_PATTERN = re.compile(
    r"(?:"
    r"hsk_[A-Za-z0-9_]{8,}"
    r"|gsk_[A-Za-z0-9]{8,}"
    r"|sk-(?:live|test|proj)?[-_]?[A-Za-z0-9]{12,}"
    r"|(?:pk|rk|sk)_(?:live|test)_[A-Za-z0-9]{8,}"
    r"|whsec_[A-Za-z0-9]{8,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[abpr]-[A-Za-z0-9-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"
    r"|(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s:/@]+:[^\s@/]+@\S+"
    r"|(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*['\"]?[^\s'\"]{6,}"
    r")",
    re.IGNORECASE,
)

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
CARD_PATTERN = re.compile(r"\b(?:\d[ -]?){13,16}\b")


def contains_secret(text: str) -> bool:
    return bool(SECRET_PATTERN.search(text or ""))


def contains_pii(text: str) -> bool:
    text = text or ""
    return bool(EMAIL_PATTERN.search(text) or CARD_PATTERN.search(text))


def redact_secrets(text: str) -> str:
    return SECRET_PATTERN.sub("[REDACTED_SECRET]", text or "")
