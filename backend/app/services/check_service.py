"""Memory Check: verify any output against project memory (Blueprint §4.2, §16.5).

1. Recall the decisions the output might violate (summary + identifiers as the query).
2. Judge (LLM, or the deterministic pattern judge when no LLM is configured).
3. Post-validate: drop findings whose record is not in the provided set or whose excerpt
   is not a substring of the content, then recompute the verdict.
The judge never learns whether the content came from a baseline or a memory run (M3).
"""

from __future__ import annotations

import hashlib
import json
import re
import time

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.tokens import count_tokens, truncate_tokens
from app.db.governed_models import CheckRun, MemoryRecord
from app.gateways.hindsight_gateway import HindsightGateway, HindsightUnavailable
from app.gateways.llm_gateway import LLMGateway
from app.gateways.project_context import BankResolver
from app.prompts.schemas import JudgeFinding, JudgeOutput
from app.prompts.templates import JUDGE_SYSTEM
from app.schemas.common import CheckResult, ConflictOut, Finding, RecordRef
from app.services import heuristics
from app.services.audit_service import AuditService
from app.services.governed_memory_service import GovernedMemoryService
from app.services.serializers import record_ref

MAX_CHECK_RECORDS = 10


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


class CheckService:
    """Evaluates code, plans or diffs against governed project decisions."""

    def __init__(
        self,
        hindsight: HindsightGateway | None = None,
        llm: LLMGateway | None = None,
        memory_service: GovernedMemoryService | None = None,
    ) -> None:
        from app.gateways.hindsight_gateway import get_hindsight_gateway
        from app.gateways.llm_gateway import get_llm_gateway

        self.hindsight = hindsight or get_hindsight_gateway()
        self.llm = llm or get_llm_gateway()
        self.memory_service = memory_service or GovernedMemoryService(self.hindsight)

    @staticmethod
    def recall_query(content: str) -> str:
        summary = heuristics.summarize_output(content)
        idents = heuristics.identifiers(content)
        body = truncate_tokens(content, 250)
        return f"{summary}\nIdentifiers: {', '.join(idents)}\n{body}".strip()

    async def check(
        self,
        db: Session,
        project_id: str,
        content: str,
        run_id: str | None = None,
    ) -> CheckResult:
        started = time.perf_counter()
        ctx = BankResolver.resolve(db, project_id)
        content = content or ""
        active = self.memory_service.get_active_records(db, project_id)
        active_map = {r.id: r for r in active}
        result: CheckResult
        try:
            if not active:
                result = CheckResult(
                    verdict="compliant",
                    message="This project has no active memory to check against.",
                    judge_mode="none",
                )
            elif not getattr(self.hindsight, "available", True):
                result = CheckResult(
                    verdict="unavailable",
                    message="Hindsight is offline, so relevant decisions cannot be recalled for Check.",
                    judge_mode="none",
                )
            else:
                result = await self._check(db, ctx, content, active, active_map, run_id)
        finally:
            AuditService.flush(db, ctx, commit=False)

        result.checked_tokens = count_tokens(content)
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        check_run = CheckRun(
            project_id=project_id,
            run_id=run_id,
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            content_preview=content[:600],
            verdict=result.verdict,
            judge_model=result.judge_model,
            violations_json=json.dumps([v.model_dump() for v in result.violations]),
            warnings_json=json.dumps([w.model_dump() for w in result.warnings]),
            conflicts_json=json.dumps([c.model_dump() for c in result.conflicts]),
            recalled_record_ids_json=json.dumps([r.id for r in result.recalled_records]),
            checked_tokens=result.checked_tokens,
            latency_ms=result.latency_ms,
        )
        db.add(check_run)
        for v in result.violations:
            record = active_map.get(v.record_id)
            if record:
                record.times_violated = (record.times_violated or 0) + 1
        AuditService.log(
            db,
            project_id,
            "CHECK",
            latency_ms=result.latency_ms,
            run_id=run_id,
            detail={
                "verdict": result.verdict,
                "violations": len(result.violations),
                "warnings": len(result.warnings),
                "judge": result.judge_mode,
                "dropped": result.dropped_findings,
            },
        )
        db.commit()
        result.id = check_run.id
        return result

    async def _check(self, db, ctx, content, active, active_map, run_id) -> CheckResult:
        try:
            outcome = await self.hindsight.recall_detailed(
                ctx,
                self.recall_query(content),
                purpose="check",
                max_tokens=2000,
                exclude_status=["superseded", "retracted"],
                expect_results=True,
                run_id=run_id,
            )
        except (HindsightUnavailable, AppError) as exc:
            return CheckResult(
                verdict="unavailable",
                message=f"Recall for Check failed: {getattr(exc, 'message', str(exc))}",
                judge_mode="none",
            )

        # Deterministic hints first: records whose check_patterns hit are always judged.
        targets: list[MemoryRecord] = [r for r in active if heuristics.pattern_hits(r, content)[0]]
        for fact in outcome.facts:
            for rid in fact.record_ids or [fact.record_id]:
                record = active_map.get(rid)
                if record and record not in targets:
                    targets.append(record)
        targets = targets[: max(MAX_CHECK_RECORDS, len([t for t in targets if heuristics.pattern_hits(t, content)[0]]))]
        recalled_refs = [RecordRef(**record_ref(r)) for r in targets]
        if not targets:
            return CheckResult(
                verdict="compliant",
                message="No recorded decision is relevant to this content.",
                judge_mode="none",
                recalled_records=[],
            )

        judge_mode = "llm"
        judge_model = getattr(self.llm, "model_large", None)
        message = None
        if not getattr(self.llm, "configured", True):
            raw = heuristics.judge(content, targets)
            judge_mode, judge_model = "heuristic", heuristics.HEURISTIC_MODEL
            message = "No LLM configured: deterministic pattern judge (check_patterns only)."
        else:
            try:
                raw = await self._llm_judge(content, targets)
            except AppError as exc:
                raw = heuristics.judge(content, targets)
                judge_mode, judge_model = "heuristic", heuristics.HEURISTIC_MODEL
                message = f"LLM judge unavailable ({exc.code}); showing deterministic pattern findings only."

        by_key = {r.id: r for r in targets}
        by_key.update({r.pill.upper(): r for r in targets})
        dropped = 0

        def validate(items: list[JudgeFinding]) -> list[tuple[MemoryRecord, JudgeFinding]]:
            nonlocal dropped
            kept: list[tuple[MemoryRecord, JudgeFinding]] = []
            seen: set[tuple[str, str]] = set()
            for item in items:
                record = by_key.get(item.record_id) or by_key.get(item.record_id.upper().strip())
                excerpt = (item.excerpt or "").strip()
                if not record or not excerpt:
                    dropped += 1
                    continue
                if excerpt not in content and _norm(excerpt) not in _norm(content):
                    dropped += 1
                    continue
                key = (record.id, _norm(excerpt)[:80])
                if key in seen:
                    continue
                seen.add(key)
                kept.append((record, item))
            return kept

        def finding(record: MemoryRecord, item: JudgeFinding) -> Finding:
            forbidden, _ = heuristics.pattern_hits(record, content)
            severity = item.severity if item.severity in ("high", "medium", "low") else "medium"
            return Finding(
                record_id=record.id,
                record_pill=record.pill,
                record_title=record.title,
                severity=severity,
                rule_statement=record.statement,
                excerpt=item.excerpt.strip(),
                explanation=item.explanation or "",
                suggested_fix=item.suggested_fix or "",
                pattern_evidence=[f"matched /{p}/" for p in forbidden[:3]],
                tentative=record.confidence_band == "low" or bool(record.tentative),
            )

        violations: list[Finding] = []
        warnings: list[Finding] = []
        for record, item in validate(raw.violations):
            f = finding(record, item)
            # Tentative (agent-proposed / low-confidence) records warn, never violate.
            (warnings if f.tentative else violations).append(f)
        for record, item in validate(raw.warnings):
            warnings.append(finding(record, item))

        conflicts: list[ConflictOut] = []
        for c in raw.conflicts:
            recs = [by_key.get(i) or by_key.get(i.upper()) for i in c.record_ids]
            recs = [r for r in recs if r]
            if len(recs) >= 2:
                conflicts.append(
                    ConflictOut(
                        record_ids=[r.id for r in recs],
                        record_pills=[r.pill for r in recs],
                        explanation=c.explanation or "Memory conflict — needs a human decision.",
                    )
                )

        severity_order = {"high": 0, "medium": 1, "low": 2}
        violations.sort(key=lambda v: severity_order.get(v.severity, 3))
        return CheckResult(
            verdict="violations" if violations else "compliant",
            message=message,
            summary=raw.summary,
            judge_mode=judge_mode,
            judge_model=judge_model,
            violations=violations,
            warnings=warnings,
            conflicts=conflicts,
            recalled_records=recalled_refs,
            dropped_findings=dropped,
        )

    async def _llm_judge(self, content: str, records: list[MemoryRecord]) -> JudgeOutput:
        payload = []
        for r in records:
            forbidden, _ = heuristics.pattern_hits(r, content)
            payload.append(
                {
                    "record_id": r.pill,
                    "type": r.type,
                    "rule": r.statement[:400],
                    "rationale": (r.rationale or "")[:300],
                    "importance": r.importance,
                    "confidence": "tentative" if r.confidence_band == "low" else r.confidence_band,
                    "pattern_hits": forbidden[:3],
                }
            )
        result = await self.llm.complete_json(
            tier="large",
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Records (data):\n{json.dumps(payload, ensure_ascii=False)}\n\n"
                        f"Content to check (data):\n<content>\n{content[:60000]}\n</content>"
                    ),
                },
            ],
            schema=JudgeOutput,
            job="judge",
            temperature=0.0,
            max_tokens=2000,
        )
        return result.parsed
