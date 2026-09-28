"""Service wiring shared by the API, the MCP server and background jobs.

Tests swap gateways with `configure(hindsight=FakeHindsight(), llm=FakeLLM())`.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.gateways.hindsight_gateway import HindsightGateway, get_hindsight_gateway
from app.gateways.llm_gateway import LLMGateway, get_llm_gateway
from app.services.brief_service import BriefService
from app.services.check_service import CheckService
from app.services.compare_service import CompareService
from app.services.eval_service import EvalService
from app.services.extraction_service import ExtractionService
from app.services.generation_service import GenerationService
from app.services.governed_memory_service import GovernedMemoryService
from app.services.metrics_service import MetricsService
from app.services.project_service import ProjectService
from app.services.reflect_service import ReflectService
from app.services.review_service import ReviewService
from app.services.seed_service import SeedService
from app.services.session_service import SessionService
from app.services.timeline_service import TimelineService


@dataclass
class Services:
    hindsight: HindsightGateway
    llm: LLMGateway
    memory: GovernedMemoryService
    projects: ProjectService
    brief: BriefService
    generation: GenerationService
    check: CheckService
    compare: CompareService
    extraction: ExtractionService
    sessions: SessionService
    review: ReviewService
    reflect: ReflectService
    timeline: TimelineService
    metrics: MetricsService
    seed: SeedService
    eval: EvalService


def build(hindsight=None, llm=None, session_factory=None) -> Services:
    hindsight = hindsight or get_hindsight_gateway()
    llm = llm or get_llm_gateway()
    memory = GovernedMemoryService(hindsight)
    projects = ProjectService(hindsight)
    brief = BriefService(hindsight, llm, memory)
    generation = GenerationService(llm, brief)
    check = CheckService(hindsight, llm, memory)
    compare = CompareService(generation, check, session_factory=session_factory)
    sessions = SessionService(generation)
    return Services(
        hindsight=hindsight,
        llm=llm,
        memory=memory,
        projects=projects,
        brief=brief,
        generation=generation,
        check=check,
        compare=compare,
        extraction=ExtractionService(hindsight, llm, memory),
        sessions=sessions,
        review=ReviewService(memory),
        reflect=ReflectService(hindsight, memory),
        timeline=TimelineService(),
        metrics=MetricsService(hindsight),
        seed=SeedService(memory, projects, sessions),
        eval=EvalService(brief),
    )


_services: Services | None = None


def services() -> Services:
    global _services
    if _services is None:
        _services = build()
    return _services


def configure(hindsight=None, llm=None, session_factory=None) -> Services:
    global _services
    _services = build(hindsight, llm, session_factory)
    return _services
