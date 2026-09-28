"""Generation output schema (blueprint 11.3). Owner: P5."""

from pydantic import BaseModel, Field


class GeneratedFile(BaseModel):
    path: str
    language: str = ""
    content: str


class GenerationOutput(BaseModel):
    summary: str
    files: list[GeneratedFile] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    followed_record_ids: list[str] = Field(default_factory=list)
