"""Renders an approved record into the retained Hindsight document (blueprint 4.1). Owner: P3."""

from __future__ import annotations

import re

from app.core.memory_conventions import (
    document_id,
    record_metadata,
    record_tags,
    retain_context,
)
from app.db.models import MemoryRecord
from app.gateways.hindsight_gateway import RetainDocument

_IDENTIFIER = re.compile(
    r"`([^`]{2,60})`"  # anything in backticks
    r"|\b([A-Za-z_][\w.]*\(\))"  # calls like stripe.webhooks.constructEvent()
    r"|\b([a-z]+[A-Z]\w+)\b"  # camelCase
    r"|\b([A-Z][a-z]+[A-Z]\w+)\b"  # PascalCase like PrismaClient
    r"|\b(\w+_\w+)\b"  # snake_case like amount_cents
    r"|(__\w[\w-]+)"  # cookie names like __Host-apx_rt
    r"|(/[\w/{}.-]+)"  # paths
)


def extract_entities(text: str, limit: int = 12) -> list[str]:
    found: list[str] = []
    for match in _IDENTIFIER.finditer(text):
        token = next(g for g in match.groups() if g)
        if token not in found:
            found.append(token)
        if len(found) == limit:
            break
    return found


def render_content(
    record: MemoryRecord, project_name: str, replaces: MemoryRecord | None = None
) -> str:
    lines = [
        f"[{record.type.upper()}] {record.title} — {project_name}",
        f"Rule: {record.statement}",
    ]
    if record.rationale:
        lines.append(f"Rationale: {record.rationale}")
    if record.applies_to:
        lines.append(f"Applies to: {', '.join(record.applies_to)}.")
    by = f" by {record.approved_by}" if record.approved_by else ""
    lines.append(f"Decided: {record.decided_at.date().isoformat()}{by}.")
    lines.append(f"Status: {record.status}.")
    if replaces is not None:
        lines.append(
            f"Replaces the decision of {replaces.decided_at.date().isoformat()}: {replaces.statement}"
        )
    return "\n".join(lines)


def tags_for(record: MemoryRecord) -> list[str]:
    return record_tags(
        type_=record.type,
        area=record.area,
        status=record.status,
        low_confidence=record.confidence < 0.4,
    )


def build_document(
    record: MemoryRecord, project_name: str, replaces: MemoryRecord | None = None
) -> RetainDocument:
    return RetainDocument(
        record_id=str(record.id),
        content=render_content(record, project_name, replaces),
        timestamp=record.decided_at.isoformat(),
        tags=tags_for(record),
        metadata=record_metadata(
            record_id=record.id,
            project_id=record.project_id,
            type_=record.type,
            area=record.area,
            importance=record.importance,
            source_session_id=record.source_session_id,
            supersedes=record.supersedes_record_id,
            stated_by=record.stated_by,
        ),
        context=retain_context(project_name),
        entities=extract_entities(f"{record.statement} {record.rationale or ''}"),
    )


__all__ = ["build_document", "document_id", "extract_entities", "render_content", "tags_for"]
