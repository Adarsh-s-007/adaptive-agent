from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

MemoryType = Literal[
    "architecture decision",
    "coding convention",
    "bug fix",
    "failed approach",
    "feature progress",
    "architecture_decision",
    "security_rule",
    "api_contract",
    "incident_fix",
    "coding_convention",
]
ProjectName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=150)
]
AgentName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)
]
MemoryContent = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=12, max_length=12000)
]
Task = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=5000)
]


class ProjectCreate(BaseModel):
    name: ProjectName
    description: str = Field(default="", max_length=2000)


class MemoryCreate(BaseModel):
    memory_type: MemoryType
    source_agent: AgentName
    content: MemoryContent
    tags: list[str] = Field(default_factory=list, max_length=12)


class RecallRequest(BaseModel):
    task: Task
    limit: int = Field(default=5, ge=1, le=10)


class AgentAnswerRequest(RecallRequest):
    agent_name: AgentName = "Agent B - fresh session"
