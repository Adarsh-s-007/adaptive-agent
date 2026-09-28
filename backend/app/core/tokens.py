"""Approximate token counting (tiktoken o200k_base, with a character fallback)."""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _encoder():
    try:
        import tiktoken

        return tiktoken.get_encoding("o200k_base")
    except Exception:  # noqa: BLE001  # pragma: no cover - offline environments without the BPE file
        return None


def count_tokens(text: str) -> int:
    if not text:
        return 0
    encoder = _encoder()
    if encoder is None:
        return max(1, len(text) // 4)
    return len(encoder.encode(text, disallowed_special=()))


def truncate_tokens(text: str, max_tokens: int) -> str:
    """Trim text to at most `max_tokens` tokens (Hindsight rejects queries over 500)."""
    encoder = _encoder()
    if encoder is None:
        return text[: max_tokens * 4]
    ids = encoder.encode(text, disallowed_special=())
    if len(ids) <= max_tokens:
        return text
    return encoder.decode(ids[:max_tokens])
