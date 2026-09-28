"""Pydantic output models for every LLM job; they double as the JSON schemas sent to the model."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ExtractedCandidate(BaseModel):
    type: str
    title: str = Field(..., max_length=120)
    statement: str
    rationale: str | None = None
    area: str | None = None
    applies_to: list[str] = Field(default_factory=list)
    evidence_quote: str
    evidence_turn_ids: list[int] = Field(default_factory=list)
    stated_by: str = "human"
    confidence: float = 0.7
    importance: int = 2

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @field_validator("importance")
    @classmethod
    def _clamp_importance(cls, value: int) -> int:
        return max(1, min(3, int(value)))


class DiscardedItem(BaseModel):
    item: str
    reason: str


class ExtractionOutput(BaseModel):
    candidates: list[ExtractedCandidate] = Field(default_factory=list)
    discarded: list[DiscardedItem] = Field(default_factory=list)


class RelationItem(BaseModel):
    candidate_index: int
    relation: str = "new"  # new · duplicate · refines · conflicts · supersedes
    target_record_id: str | None = None
    reason: str = ""


class RelationOutput(BaseModel):
    relations: list[RelationItem] = Field(default_factory=list)


class ApplicabilityItem(BaseModel):
    record_id: str
    applies: bool = False
    reason: str = ""


class ApplicabilityResponse(BaseModel):
    selections: list[ApplicabilityItem] = Field(default_factory=list)


class GeneratedFile(BaseModel):
    path: str
    language: str = "text"
    content: str = ""


class GenerationOutput(BaseModel):
    summary: str
    files: list[GeneratedFile] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    followed_record_ids: list[str] = Field(default_factory=list)

    @field_validator("files", mode="before")
    @classmethod
    def _coerce_files(cls, value):
        # Tolerate models that return plain paths.
        if isinstance(value, list):
            return [{"path": v, "language": "text", "content": ""} if isinstance(v, str) else v for v in value]
        return value


class JudgeFinding(BaseModel):
    record_id: str
    severity: str = "medium"  # high · medium · low
    excerpt: str
    explanation: str = ""
    suggested_fix: str = ""


class JudgeConflict(BaseModel):
    record_ids: list[str] = Field(default_factory=list)
    explanation: str = ""


class JudgeOutput(BaseModel):
    summary: str = ""
    verdict: str = "compliant"
    violations: list[JudgeFinding] = Field(default_factory=list)
    warnings: list[JudgeFinding] = Field(default_factory=list)
    conflicts: list[JudgeConflict] = Field(default_factory=list)
