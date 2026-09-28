"""ID generation utilities including UUIDv7 support for ProjectPulse."""

from __future__ import annotations

import os
import time
import uuid


def generate_uuidv7() -> str:
    """Generate a UUIDv7 (time-ordered UUID) per RFC 9562 / Blueprint §14."""
    # 48 bits of millisecond timestamp
    timestamp_ms = int(time.time() * 1000)
    time_high = (timestamp_ms >> 16) & 0xFFFFFFFF
    time_mid = timestamp_ms & 0xFFFF

    # 12 bits random for ver_and_rand
    rand_a = int.from_bytes(os.urandom(2), byteorder="big") & 0x0FFF
    time_hi_and_version = (7 << 12) | rand_a

    # 14 bits random for var_and_rand
    rand_b = int.from_bytes(os.urandom(2), byteorder="big") & 0x3FFF
    clock_seq_hi_and_reserved = 0x80 | (rand_b >> 8)
    clock_seq_low = rand_b & 0xFF

    # 48 bits random node
    node = int.from_bytes(os.urandom(6), byteorder="big")

    val = (
        (time_high << 96)
        | (time_mid << 80)
        | (time_hi_and_version << 64)
        | (clock_seq_hi_and_reserved << 56)
        | (clock_seq_low << 48)
        | node
    )
    return str(uuid.UUID(int=val))


def generate_record_pill(record_id: str) -> str:
    """Generate a human-readable record pill like 'MEM-7F3A' from a record ID."""
    clean = record_id.replace("-", "").upper()
    suffix = clean[:4] if len(clean) >= 4 else clean.ljust(4, "0")
    return f"MEM-{suffix}"
