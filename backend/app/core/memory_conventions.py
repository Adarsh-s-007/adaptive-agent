"""Canonical conventions for Hindsight document IDs, tags, metadata and content (Blueprint §4.1, §15.3)."""

from __future__ import annotations

from datetime import datetime

RETAIN_CONTEXT = "approved engineering decision record for software project {name}"


def format_document_id(record_id: str) -> str:
    """One record = one Hindsight document: `mem_<record_id>` (idempotent retain)."""
    return f"mem_{record_id}"


def record_id_from_document(document_id: str | None) -> str | None:
    if document_id and document_id.startswith("mem_"):
        return document_id[4:]
    return None


def build_tags(
    project_id: str,
    memory_type: str,
    area: str | None = None,
    status: str = "active",
    confidence_band: str = "high",
    extra_tags: list[str] | None = None,
) -> list[str]:
    """Tag set stored on every document. `project:` and `status:` drive recall filtering."""
    tags = [f"project:{project_id}", f"type:{memory_type}", f"status:{status}"]
    if area:
        tags.append(f"area:{area}")
    if confidence_band == "low":
        tags.append("confidence:low")
    for tag in extra_tags or []:
        clean = tag.strip().lower()
        if (
            clean
            and not clean.startswith(("project:", "status:", "type:"))
            and clean not in tags
            and len(clean) <= 60
        ):
            tags.append(clean)
    return tags


def build_metadata(
    record_id: str,
    project_id: str,
    memory_type: str,
    area: str | None = None,
    importance: int = 3,
    source_session_id: str | None = None,
    supersedes: str | None = None,
    stated_by: str | None = None,
) -> dict[str, str]:
    """Hindsight metadata: strings only, empty strings for absent values (§15.3)."""
    return {
        "record_id": str(record_id),
        "project_id": str(project_id),
        "type": str(memory_type),
        "area": str(area or ""),
        "importance": str(importance),
        "source_session_id": str(source_session_id or ""),
        "supersedes": str(supersedes or ""),
        "stated_by": str(stated_by or ""),
    }


def format_context_string(project_name: str, area: str | None = None) -> str:
    """Kept constant per project because context shapes Hindsight's extraction."""
    return RETAIN_CONTEXT.format(name=project_name)


def render_record_content(
    title: str,
    statement: str,
    memory_type: str,
    rationale: str | None = None,
    area: str | None = None,
    supersedes_ref: str | None = None,
    *,
    project_name: str | None = None,
    applies_to: list[str] | None = None,
    decided_at: datetime | None = None,
    session_title: str | None = None,
    decided_by: str | None = None,
    status: str = "active",
) -> str:
    """Render the fixed record template that becomes the Hindsight document text."""
    header = f"[{memory_type}] {title.strip()}"
    if project_name:
        header += f" — {project_name}"
    lines = [header, f"Rule: {statement.strip()}"]
    if rationale and rationale.strip():
        lines.append(f"Rationale: {rationale.strip()}")
    scope = [s for s in (applies_to or []) if s]
    if scope:
        lines.append(f"Applies to: {', '.join(scope)}.")
    elif area and area.strip():
        lines.append(f"Applies to: {area.strip()}.")
    if decided_at:
        decided = f"Decided: {decided_at.date().isoformat()}"
        if session_title:
            decided += f' in session "{session_title}"'
        if decided_by:
            decided += f" by {decided_by}"
        lines.append(decided + ".")
    lines.append(f"Status: {status}.")
    if supersedes_ref and supersedes_ref.strip():
        lines.append(f"Replaces the decision of {supersedes_ref.strip()}")
    return "\n".join(lines)
