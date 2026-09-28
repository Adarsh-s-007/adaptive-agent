"""Frozen Hindsight document conventions (contract C-4). Owner: P1.

Retain (P3 via P2's gateway), recall mapping (P2) and post-filters (P5/P6) must all use
these helpers so tags and metadata stay consistent.
"""

from __future__ import annotations

import uuid

RETIRED_STATUSES = ("superseded", "retracted")


def document_id(record_id: uuid.UUID | str) -> str:
    return f"mem_{record_id}"


def record_id_from_document(doc_id: str | None) -> str | None:
    if doc_id and doc_id.startswith("mem_"):
        return doc_id[4:]
    return None


def record_tags(*, type_: str, area: str, status: str, low_confidence: bool = False) -> list[str]:
    tags = [f"type:{type_}", f"area:{area}", f"status:{status}"]
    if low_confidence:
        tags.append("confidence:low")
    return tags


def record_metadata(
    *,
    record_id: uuid.UUID | str,
    project_id: uuid.UUID | str,
    type_: str,
    area: str,
    importance: int,
    source_session_id: uuid.UUID | str | None,
    supersedes: uuid.UUID | str | None,
    stated_by: str,
) -> dict[str, str]:
    """Hindsight drops null keys, so absent values are empty strings."""
    return {
        "record_id": str(record_id),
        "project_id": str(project_id),
        "type": type_,
        "area": area,
        "importance": str(importance),
        "source_session_id": str(source_session_id or ""),
        "supersedes": str(supersedes or ""),
        "stated_by": stated_by,
    }


def retain_context(project_name: str) -> str:
    return f"approved engineering decision record for software project {project_name}"


def retired_tag_groups() -> list[dict]:
    """Recall filter that excludes superseded and retracted records [VERIFY in HS-1]."""
    return [{"not": {"tags": [f"status:{s}" for s in RETIRED_STATUSES], "match": "any_strict"}}]
