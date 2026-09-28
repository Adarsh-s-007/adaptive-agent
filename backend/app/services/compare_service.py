"""Compare Mode: a controlled experiment with one variable — the project memory block (§11).

Both sides use the same model, temperature 0, the same system prompt layers 1, 2 and 4,
and the same blind Memory Check. The job runs in the background and reports stages
(baseline_done · brief_done · memory_done · checks_done) that the UI streams over SSE.
"""

from __future__ import annotations

import asyncio
import json
import statistics
from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError, AppErrorCode, not_found
from app.core.logging import get_logger
from app.db.governed_models import CheckRun, ComparisonRun, TaskRun
from app.schemas.common import BriefResult, CheckResult, CompareResult, TaskRunOut
from app.services.check_service import CheckService
from app.services.generation_service import GenerationService
from app.services.serializers import iso, loads

log = get_logger("compare")

SessionFactory = Callable[[], Any]


def _counted(check: CheckResult | None) -> int:
    """Violation delta counts high + medium violations (§20)."""
    if not check or check.verdict == "unavailable":
        return 0
    return sum(1 for v in check.violations if v.severity in ("high", "medium"))


class CompareService:
    def __init__(
        self,
        generation_service: GenerationService | None = None,
        check_service: CheckService | None = None,
        session_factory: SessionFactory | None = None,
    ) -> None:
        from app.db.database import SessionLocal

        self.generation_service = generation_service or GenerationService()
        self.check_service = check_service or CheckService()
        self.session_factory = session_factory or SessionLocal
        self._tasks: set[asyncio.Task] = set()

    # ----------------------------------------------------------------- public
    async def compare(self, db: Session, project_id: str, task: str, repeats: int = 1) -> CompareResult:
        """Run a comparison to completion in the caller's session (tests, MCP, scripts)."""
        comparison = self._create(db, project_id, task, repeats)
        await self._execute(comparison.id, lambda: nullcontext(db), parallel=False)
        db.expire_all()
        return self.load(db, project_id, comparison.id)

    def start(self, db: Session, project_id: str, task: str, repeats: int = 1) -> ComparisonRun:
        """Create the comparison row and run it in the background."""
        comparison = self._create(db, project_id, task, repeats)
        factory = self.session_factory

        @contextmanager
        def open_session():
            session = factory()
            try:
                yield session
            finally:
                session.close()

        job = asyncio.create_task(self._execute(comparison.id, open_session, parallel=True))
        self._tasks.add(job)
        job.add_done_callback(self._tasks.discard)
        return comparison

    def _create(self, db: Session, project_id: str, task: str, repeats: int) -> ComparisonRun:
        llm = self.generation_service.llm
        if not getattr(llm, "configured", True):
            raise AppError(
                AppErrorCode.LLM_UNAVAILABLE,
                "Compare needs an LLM for generation. Set GROQ_API_KEY on the server.",
                status_code=503,
            )
        comparison = ComparisonRun(
            project_id=project_id,
            task=task.strip(),
            repeats=3 if repeats >= 3 else 1,
            status="running",
            stage="queued",
        )
        db.add(comparison)
        db.commit()
        db.refresh(comparison)
        return comparison

    # ---------------------------------------------------------------- pipeline
    async def _execute(self, comparison_id: str, open_session, *, parallel: bool) -> None:
        try:
            await self._pipeline(comparison_id, open_session, parallel)
        except Exception as exc:
            log.exception("comparison %s failed", comparison_id)
            with open_session() as db:
                row = db.get(ComparisonRun, comparison_id)
                if row:
                    row.status = "failed"
                    row.stage = "failed"
                    row.error_json = json.dumps(
                        {
                            "code": getattr(exc, "code", AppErrorCode.INTERNAL_ERROR),
                            "message": getattr(exc, "message", str(exc)),
                        }
                    )
                    row.completed_at = datetime.now(timezone.utc)
                    db.commit()

    def _set_stage(self, open_session, comparison_id: str, stage: str, **fields) -> None:
        with open_session() as db:
            row = db.get(ComparisonRun, comparison_id)
            if row:
                row.stage = stage
                for key, value in fields.items():
                    setattr(row, key, value)
                db.commit()

    async def _pipeline(self, comparison_id: str, open_session, parallel: bool) -> None:
        with open_session() as db:
            row = db.get(ComparisonRun, comparison_id)
            project_id, task, repeats = row.project_id, row.task, row.repeats or 1

        gen = self.generation_service

        async def baseline_side() -> list[TaskRunOut]:
            runs = []
            for i in range(repeats):
                with open_session() as db:
                    runs.append(
                        await gen.run(db, project_id, task, mode="baseline", comparison_id=comparison_id, repeat_index=i)
                    )
            self._set_stage(open_session, comparison_id, "baseline_done")
            return runs

        async def memory_side() -> tuple[BriefResult, list[TaskRunOut]]:
            with open_session() as db:
                brief = await gen.brief_service.build_brief(db, project_id, task)
            self._set_stage(open_session, comparison_id, "brief_done")
            runs = []
            if brief.status == "memory_unavailable":
                with open_session() as db:
                    runs.append(self._blocked_run(db, project_id, task, comparison_id, brief))
            else:
                for i in range(repeats):
                    with open_session() as db:
                        runs.append(
                            await gen.run(
                                db, project_id, task, mode="memory", comparison_id=comparison_id,
                                repeat_index=i, brief=brief,
                            )
                        )
            self._set_stage(open_session, comparison_id, "memory_done")
            return brief, runs

        if parallel:
            baseline_runs, (brief, memory_runs) = await asyncio.gather(baseline_side(), memory_side())
        else:
            baseline_runs = await baseline_side()
            brief, memory_runs = await memory_side()

        async def check(run: TaskRunOut) -> CheckResult | None:
            if run.status != "ok":
                return None
            content = gen.output_as_text(run.output)
            with open_session() as db:
                return await self.check_service.check(db, project_id, content, run_id=run.id)

        all_runs = baseline_runs + memory_runs
        if parallel:
            checks = await asyncio.gather(*(check(r) for r in all_runs))
        else:
            checks = [await check(r) for r in all_runs]
        baseline_checks = checks[: len(baseline_runs)]
        memory_checks = checks[len(baseline_runs) :]

        base_counts = [_counted(c) for c, r in zip(baseline_checks, baseline_runs) if r.status == "ok"]
        mem_counts = [_counted(c) for c, r in zip(memory_checks, memory_runs) if r.status == "ok"]
        mean_base = statistics.mean(base_counts) if base_counts else 0.0
        mean_mem = statistics.mean(mem_counts) if mem_counts else 0.0
        applied = len(brief.applied)
        model = next((r.model for r in all_runs if r.model), None)
        base_prompt = [r.usage.get("prompt_tokens", 0) for r in baseline_runs if r.status == "ok"]
        mem_prompt = [r.usage.get("prompt_tokens", 0) for r in memory_runs if r.status == "ok"]
        followed = sorted({rid for r in memory_runs for rid in r.output.followed_record_ids})
        errors = [r.error for r in all_runs if r.error]
        summary: dict[str, Any] = {
            "violations_baseline_per_run": base_counts,
            "violations_memory_per_run": mem_counts,
            "mean_violations_baseline": round(mean_base, 2),
            "mean_violations_memory": round(mean_mem, 2),
            "violation_delta": round(mean_base - mean_mem, 2),
            "records_recalled": len(brief.recalled),
            "records_applied": applied,
            "records_filtered": len(brief.filtered),
            "records_followed": len(followed),
            "memory_utilisation": round(len(followed) / applied, 2) if applied else None,
            "injected_tokens": brief.injected_tokens,
            "all_records_tokens": brief.all_records_tokens,
            "prompt_token_difference": (
                round(statistics.mean(mem_prompt) - statistics.mean(base_prompt)) if base_prompt and mem_prompt else None
            ),
            "brief_status": brief.status,
            "filter_mode": brief.filter_mode,
            "judge_modes": sorted({c.judge_mode for c in checks if c}),
            "recall_ms": brief.recall_ms,
            "filter_ms": brief.filter_ms,
            "baseline_latency_ms": [r.latency_ms for r in baseline_runs],
            "memory_latency_ms": [r.latency_ms for r in memory_runs],
            "errors": errors,
        }
        fairness = {
            "model": model,
            "temperature": 0,
            "identical_system_prompt_layers": ["role", "project_profile"],
            "only_difference": "<project_memory> block",
            "blind_check": True,
            "baseline_hindsight_calls": 0,
            "line": (
                f"Both runs: {model or 'same model'}, temperature 0, identical system prompt. "
                f"Right pane adds {applied} record{'s' if applied != 1 else ''} ({brief.injected_tokens} tokens)."
            ),
        }
        failed = bool(all_runs) and all(r.status != "ok" for r in all_runs)
        with open_session() as db:
            row = db.get(ComparisonRun, comparison_id)
            row.baseline_run_ids_json = json.dumps([r.id for r in baseline_runs])
            row.memory_run_ids_json = json.dumps([r.id for r in memory_runs])
            row.baseline_run_id = baseline_runs[0].id if baseline_runs else None
            row.memory_run_id = memory_runs[0].id if memory_runs else None
            row.baseline_check_id = baseline_checks[0].id if baseline_checks and baseline_checks[0] else None
            row.memory_check_id = memory_checks[0].id if memory_checks and memory_checks[0] else None
            row.violations_baseline = round(mean_base)
            row.violations_memory = round(mean_mem)
            row.violation_delta = round(mean_base - mean_mem)
            row.applied_count = applied
            row.injected_tokens = brief.injected_tokens
            row.summary_json = json.dumps(summary, default=str)
            row.fairness_json = json.dumps(fairness)
            row.status = "failed" if failed else "completed"
            row.stage = "failed" if failed else "checks_done"
            if failed and errors:
                row.error_json = json.dumps(errors[0], default=str)
            row.completed_at = datetime.now(timezone.utc)
            db.commit()

    def _blocked_run(
        self, db: Session, project_id: str, task: str, comparison_id: str, brief: BriefResult
    ) -> TaskRunOut:
        """Memory-aware run blocked because Hindsight is unavailable — shown honestly."""
        error = {"code": AppErrorCode.HINDSIGHT_UNAVAILABLE, "message": brief.message or "Memory unavailable."}
        run = TaskRun(
            project_id=project_id,
            comparison_id=comparison_id,
            mode="memory",
            task=task,
            status="blocked",
            error_json=json.dumps(error),
            summary="",
            brief_snapshot_json=brief.model_dump_json(),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        from app.schemas.common import RunOutput

        return TaskRunOut(
            id=run.id,
            project_id=project_id,
            comparison_id=comparison_id,
            mode="memory",
            task=task,
            status="blocked",
            error=error,
            output=RunOutput(summary=""),
            brief=brief,
            created_at=iso(run.created_at) or "",
        )

    # ------------------------------------------------------------------- read
    def load(self, db: Session, project_id: str, comparison_id: str) -> CompareResult:
        row = db.get(ComparisonRun, comparison_id)
        if not row or row.project_id != project_id:
            raise not_found("Comparison")

        def runs(ids: list[str]) -> list[TaskRunOut]:
            out = []
            for rid in ids:
                run = db.get(TaskRun, rid)
                if run:
                    out.append(self.run_out(run))
            return out

        def checks(run_list: list[TaskRunOut]) -> list[CheckResult]:
            out = []
            for run in run_list:
                check = (
                    db.query(CheckRun).filter(CheckRun.run_id == run.id).order_by(CheckRun.created_at.desc()).first()
                )
                out.append(self.check_out(check) if check else None)
            return out

        baseline_runs = runs(loads(row.baseline_run_ids_json, []))
        memory_runs = runs(loads(row.memory_run_ids_json, []))
        baseline_checks = checks(baseline_runs)
        memory_checks = checks(memory_runs)
        summary = loads(row.summary_json, {})
        return CompareResult(
            id=row.id,
            status=row.status,
            stage=row.stage,
            task=row.task,
            repeats=row.repeats or 1,
            baseline_run=baseline_runs[0] if baseline_runs else None,
            memory_run=memory_runs[0] if memory_runs else None,
            baseline_check=baseline_checks[0] if baseline_checks else None,
            memory_check=memory_checks[0] if memory_checks else None,
            baseline_runs=baseline_runs,
            memory_runs=memory_runs,
            baseline_checks=[c for c in baseline_checks if c],
            memory_checks=[c for c in memory_checks if c],
            violations_baseline=summary.get("mean_violations_baseline", row.violations_baseline),
            violations_memory=summary.get("mean_violations_memory", row.violations_memory),
            violation_delta=summary.get("violation_delta", row.violation_delta),
            applied_count=row.applied_count,
            injected_tokens=row.injected_tokens,
            summary=summary,
            fairness=loads(row.fairness_json, {}),
            error=loads(row.error_json, None),
            created_at=iso(row.created_at) or "",
        )

    @staticmethod
    def run_out(run: TaskRun) -> TaskRunOut:
        from app.schemas.common import GeneratedFileOut, RunOutput

        brief = loads(run.brief_snapshot_json, None)
        return TaskRunOut(
            id=run.id,
            project_id=run.project_id,
            session_id=run.session_id,
            comparison_id=run.comparison_id,
            repeat_index=run.repeat_index or 0,
            mode=run.mode,
            task=run.task,
            status=run.status or "ok",
            error=loads(run.error_json, None),
            model=run.model,
            output=RunOutput(
                summary=run.summary or "",
                files=[GeneratedFileOut(**f) if isinstance(f, dict) else GeneratedFileOut(path=str(f)) for f in loads(run.output_files_json, [])],
                notes=loads(run.output_notes_json, []),
                followed_record_ids=loads(run.followed_record_ids_json, []),
            ),
            brief=BriefResult(**brief) if isinstance(brief, dict) else None,
            usage={"prompt_tokens": run.prompt_tokens, "completion_tokens": run.completion_tokens},
            injected_tokens=run.injected_tokens or 0,
            recall_ms=run.recall_ms or 0,
            filter_ms=run.filter_ms or 0,
            llm_ms=run.llm_ms or 0,
            latency_ms=run.latency_ms or 0,
            created_at=iso(run.created_at) or "",
        )

    @staticmethod
    def check_out(check: CheckRun) -> CheckResult:
        from app.schemas.common import ConflictOut, Finding

        verdict = {"pass": "compliant", "fail": "violations"}.get(check.verdict, check.verdict)

        def findings(raw: str) -> list[Finding]:
            out = []
            for item in loads(raw, []):
                if isinstance(item, dict) and "record_id" in item:
                    out.append(Finding(**{k: v for k, v in item.items() if k in Finding.model_fields}))
            return out

        conflicts = [
            ConflictOut(**c) for c in loads(check.conflicts_json, []) if isinstance(c, dict)
        ]
        return CheckResult(
            id=check.id,
            verdict=verdict,
            judge_model=check.judge_model,
            judge_mode="heuristic" if (check.judge_model or "").startswith("heuristic") else "llm",
            violations=findings(check.violations_json),
            warnings=findings(check.warnings_json),
            conflicts=conflicts,
            checked_tokens=check.checked_tokens,
            latency_ms=check.latency_ms,
        )
