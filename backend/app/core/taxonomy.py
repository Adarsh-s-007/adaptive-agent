"""The eight-type memory taxonomy (Blueprint §6.1) and lifecycle vocabularies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryTypeSpec:
    key: str
    label: str
    default_importance: int
    purpose: str


MEMORY_TYPES: dict[str, MemoryTypeSpec] = {
    spec.key: spec
    for spec in (
        MemoryTypeSpec("decision", "Decision", 3, "A chosen design with rationale"),
        MemoryTypeSpec(
            "security_constraint", "Security constraint", 3, "A hard security/compliance rule"
        ),
        MemoryTypeSpec("convention", "Convention", 2, "How this repository does things"),
        MemoryTypeSpec("api_contract", "API contract", 2, "An interface shape other code relies on"),
        MemoryTypeSpec("incident", "Incident", 3, "Symptom, root cause and the preventing rule"),
        MemoryTypeSpec(
            "failed_approach", "Failed approach", 3, "What was tried, why it failed, what replaced it"
        ),
        MemoryTypeSpec("deployment", "Deployment", 2, "Build, release and runtime constraints"),
        MemoryTypeSpec("preference", "Preference", 1, "A team-level working agreement"),
    )
}

# Types used by the MCP-first MVP and earlier seeds, mapped onto the taxonomy.
LEGACY_TYPE_MAP: dict[str, str] = {
    "architecture_decision": "decision",
    "architecture decision": "decision",
    "security_rule": "security_constraint",
    "incident_fix": "incident",
    "bug fix": "incident",
    "coding_convention": "convention",
    "coding convention": "convention",
    "coding_standard": "convention",
    "data_model": "decision",
    "data_contract": "api_contract",
    "performance_rule": "decision",
    "operational_standard": "deployment",
    "operational_rule": "deployment",
    "dependency_rule": "convention",
    "failed approach": "failed_approach",
    "feature progress": "decision",
}

RECORD_STATUSES = ("active", "superseded", "retracted")
RETIRED_STATUSES = ("superseded", "retracted")
RETAIN_STATES = ("pending", "retained", "failed", "retag_pending")
RELATIONS = ("new", "duplicate", "refines", "conflicts", "supersedes")
CANDIDATE_STATUSES = ("pending", "approved", "rejected", "auto_rejected")
STATED_BY = ("human", "agent", "both")


def normalize_type(value: str | None) -> str:
    """Map any legacy or free-form type onto the eight-type taxonomy."""
    if not value:
        return "decision"
    key = value.strip().lower()
    if key in MEMORY_TYPES:
        return key
    return LEGACY_TYPE_MAP.get(key, LEGACY_TYPE_MAP.get(key.replace("_", " "), "decision"))


def is_known_type(value: str | None) -> bool:
    if not value:
        return False
    key = value.strip().lower()
    return key in MEMORY_TYPES or key in LEGACY_TYPE_MAP


def default_importance(memory_type: str) -> int:
    spec = MEMORY_TYPES.get(normalize_type(memory_type))
    return spec.default_importance if spec else 2


def confidence_band(confidence: float) -> str:
    """Three honest bands instead of false-precision numbers (Blueprint §5.4)."""
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.4:
        return "medium"
    return "low"


def slugify_area(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in value.strip().lower()).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned[:40] or None
