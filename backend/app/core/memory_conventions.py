"""Canonical conventions for Hindsight document IDs, tags, metadata, and templates (C-4)."""

from __future__ import annotations


def format_document_id(record_id: str) -> str:
    """Format Hindsight document ID: 'mem_<record_id>'."""
    return f"mem_{record_id}"


def build_tags(
    project_id: str,
    memory_type: str,
    area: str | None = None,
    status: str = "active",
    confidence_band: str = "high",
    extra_tags: list[str] | None = None,
) -> list[str]:
    """Build normalized tag set for Hindsight storage and recall."""
    tags = [
        f"project:{project_id}",
        f"type:{memory_type}",
        f"status:{status}",
    ]
    if area:
        tags.append(f"area:{area}")
    if confidence_band == "low":
        tags.append("confidence:low")
    if extra_tags:
        for t in extra_tags:
            clean = t.strip().lower()
            if clean and not clean.startswith("project:") and clean not in tags:
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
    """Build Hindsight metadata dictionary where all values are strings."""
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
    """Format contextual description for memory retention and reflection."""
    if area:
        return f"Engineering record for {project_name} within subsystem '{area}'."
    return f"Engineering record for {project_name}."


def render_record_content(
    title: str,
    statement: str,
    memory_type: str,
    rationale: str | None = None,
    area: str | None = None,
    supersedes_ref: str | None = None,
) -> str:
    """Render canonical content template per Blueprint §4.1."""
    parts = [
        f"[{memory_type}] {title.strip()}",
        "",
        "Rule / Decision:",
        statement.strip(),
    ]
    if rationale and rationale.strip():
        parts.extend(["", "Rationale & Context:", rationale.strip()])
    if area and area.strip():
        parts.extend(["", f"Applied scope: {area.strip()}"])
    if supersedes_ref and supersedes_ref.strip():
        parts.extend(["", f"Replaces the decision of: {supersedes_ref.strip()}"])
    return "\n".join(parts)
