"""Compare Service: Parallel baseline vs memory-aware execution and blind checks (CP-1)."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.db.governed_models import ComparisonRun
from app.schemas.common import CompareResult
from app.services.check_service import CheckService
from app.services.generation_service import GenerationService


class CompareService:
    """Orchestrates side-by-side comparative trials between baseline and memory agents."""

    def __init__(
        self,
        generation_service: GenerationService | None = None,
        check_service: CheckService | None = None,
    ) -> None:
        self.generation_service = generation_service or GenerationService()
        self.check_service = check_service or CheckService()

    async def compare(
        self,
        db: Session,
        project_id: str,
        task: str,
    ) -> CompareResult:
        # 1. Run baseline and memory generation
        # We run both generations
        baseline_run = await self.generation_service.run(db, project_id, task, mode="baseline")
        memory_run = await self.generation_service.run(db, project_id, task, mode="memory")

        # 2. Run blind checks on both outputs
        baseline_content = f"{baseline_run.output.summary}\n" + "\n".join(baseline_run.output.notes)
        memory_content = f"{memory_run.output.summary}\n" + "\n".join(memory_run.output.notes)

        baseline_check = await self.check_service.check(db, project_id, baseline_content, run_id=baseline_run.id)
        memory_check = await self.check_service.check(db, project_id, memory_content, run_id=memory_run.id)

        # 3. Calculate metrics
        v_base = len(baseline_check.violations)
        v_mem = len(memory_check.violations)
        v_delta = v_base - v_mem  # Positive means memory agent committed fewer violations!

        applied_count = len(memory_run.brief.applied) if memory_run.brief and memory_run.brief.applied else 0
        injected_tokens = memory_run.brief.injected_tokens if memory_run.brief else 0

        fairness = {
            "prompt_model_identical": True,
            "blind_check": True,
            "baseline_recalled_records": 0,
            "temperature": 0.0,
        }

        # 4. Persist ComparisonRun
        comp_run = ComparisonRun(
            project_id=project_id,
            task=task,
            status="completed",
            stage="done",
            baseline_run_id=baseline_run.id,
            memory_run_id=memory_run.id,
            violations_baseline=v_base,
            violations_memory=v_mem,
            violation_delta=v_delta,
            applied_count=applied_count,
            injected_tokens=injected_tokens,
            fairness_json=json.dumps(fairness),
        )
        db.add(comp_run)
        db.commit()
        db.refresh(comp_run)

        return CompareResult(
            id=comp_run.id,
            status="completed",
            stage="done",
            baseline_run=baseline_run,
            memory_run=memory_run,
            baseline_check=baseline_check,
            memory_check=memory_check,
            violations_baseline=v_base,
            violations_memory=v_mem,
            violation_delta=v_delta,
            applied_count=applied_count,
            injected_tokens=injected_tokens,
            fairness=fairness,
            created_at=comp_run.created_at.isoformat(),
        )
