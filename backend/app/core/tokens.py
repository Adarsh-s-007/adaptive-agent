"""Approximate token counts for injected memory (blueprint section 20). Owner: P1."""

from functools import lru_cache


@lru_cache
def _encoding():
    import tiktoken

    return tiktoken.get_encoding("o200k_base")


def count_tokens(text: str) -> int:
    try:
        return len(_encoding().encode(text))
    except Exception:  # encoding download unavailable offline
        return max(1, len(text) // 4)
