"""Memory Check Service: Judge model, post-validation against hallucination, pattern evidence (CK-1, CK-2)."""

from __future__ import annotations

import json
import re
import time

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.governed_models import CheckRun, MemoryRecord
from app.gateways.hindsight_gateway import HindsightGateway
from app.gateways.llm_gateway import LLMGateway
from app.gateways.project_context import BankResolver
from app.schemas.common import CheckResult, RecordRef, ViolationOut
from app.services.governed_memory_service import GovernedMemoryService


class RawViolation(BaseModel):
    record_id: str
    severity: str = "high"  # high, medium, low
    excerpt: str
    explanation: str
    suggested_fix: str


class JudgeResponse(BaseModel):
    verdict: str  # pass, fail, warn, conflict
    violations: list[RawViolation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class CheckService:
    """Evaluates agent-generated code or diffs against governed project decisions."""

    def __init__(
        self,
        hindsight: HindsightGateway | None = None,
        llm: LLMGateway | None = None,
        memory_service: GovernedMemoryService | None = None,
    ) -> None:
        self.hindsight = hindsight or HindsightGateway()
        self.llm = llm or LLMGateway()
        self.memory_service = memory_service or GovernedMemoryService(self.hindsight)

    async def check(
        self,
        db: Session,
        project_id: str,
        content: str,
        run_id: str | None = None,
    ) -> CheckResult:
        start_time = time.perf_counter()
        ctx = BankResolver.resolve(db, project_id)

        # 1. Recall matching records
        try:
            recalled_facts = await self.hindsight.recall(
                ctx=ctx,
                query=content[:400],
                purpose="check",
                max_tokens=2000,
                exclude_status=["superseded", "retracted"],
            )
            recalled_ids = list({f.record_id for f in recalled_facts})
        except Exception:
            recalled_ids = []

        # Also include active records for safety
        active_records = self.memory_service.get_active_records(db, project_id)
        active_map = {r.id: r for r in active_records}

        target_records: list[MemoryRecord] = []
        for rid in recalled_ids:
            if rid in active_map and active_map[rid] not in target_records:
                target_records.append(active_map[rid])
        
        # If few found via recall, add top active baseline records
        for r in active_records:
            if r not in target_records:
                target_records.append(r)
            if len(target_records) >= 8:
                break

        if not target_records:
            # No rules to violate
            return CheckResult(
                verdict="pass",
                violations=[],
                warnings=[],
                conflicts=[],
                recalled_records=[],
                checked_tokens=len(content.split()),
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )

        # 2. Build Judge prompt
        rules_payload = [
            {
                "id": r.id,
                "pill": r.pill,
                "type": r.type,
                "title": r.title,
                "statement": r.statement,
                "area": r.area,
            }
            for r in target_records
        ]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a strict compliance judge evaluating code or text against approved engineering rules. "
                    "Report any violation where the code contradicts a rule. "
                    "For every violation, the 'record_id' MUST match one from the provided list, and "
                    "'excerpt' MUST be an exact verbatim substring from the tested content."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Rules:\n{json.dumps(rules_payload, ensure_ascii=False)}\n\n"
                    f"Content to Check:\n{content}"
                ),
            },
        ]

        try:
            llm_res = await self.llm.complete_json(
                tier="large",
                messages=messages,
                schema=JudgeResponse,
                job="judge",
                temperature=0.0,
            )
            judge_data: JudgeResponse = llm_res.parsed
        except Exception:
            # Deterministic local fallback if LLM offline
            judge_data = self._local_heuristic_check(content, target_records)

        # 3. Post-validation (CK-1): Drop hallucinated IDs and non-substring excerpts!
        valid_violations: list[ViolationOut] = []
        valid_record_ids = {r.id for r in target_records}

        for v in judge_data.violations:
            # Check 1: Record ID must exist in provided set
            if v.record_id not in valid_record_ids:
                continue

            # Check 2: Excerpt must be an exact substring of content
            if v.excerpt not in content:
                continue

            rec = active_map[v.record_id]

            # Check 3: Evaluate check_patterns for pattern evidence (CK-2)
            pattern_evidence: list[str] = []
            try:
                patterns: list[str] = json.loads(rec.check_patterns_json or "[]")
                for pat in patterns:
                    if re.search(pat, content, re.IGNORECASE):
                        pattern_evidence.append(f"Matched pattern /{pat}/")
            except Exception:
                pass

            valid_violations.append(
                ViolationOut(
                    record_id=rec.id,
                    record_pill=rec.pill,
                    severity=v.severity,
                    rule_statement=rec.statement,
                    excerpt=v.excerpt,
                    explanation=v.explanation,
                    suggested_fix=v.suggested_fix,
                    pattern_evidence=pattern_evidence,
                )
            )

        # Recompute verdict after post-validation
        final_verdict = "pass"
        if valid_violations:
            final_verdict = "fail"
        elif judge_data.conflicts:
            final_verdict = "conflict"
        elif judge_data.warnings:
            final_verdict = "warn"

        recalled_refs = [
            RecordRef(
                id=r.id,
                pill=r.pill,
                type=r.type,
                title=r.title,
                statement=r.statement,
                area=r.area,
                importance=r.importance,
                status=r.status,
                confidence_band=r.confidence_band,
                decided_at=r.decided_at.isoformat() if r.decided_at else None,
            )
            for r in target_records
        ]

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        # Persist CheckRun
        check_run = CheckRun(
            project_id=project_id,
            run_id=run_id,
            verdict=final_verdict,
            violations_json=json.dumps([v.model_dump() for v in valid_violations]),
            warnings_json=json.dumps(judge_data.warnings),
            conflicts_json=json.dumps(judge_data.conflicts),
            recalled_record_ids_json=json.dumps([r.id for r in target_records]),
            checked_tokens=len(content.split()),
            latency_ms=latency_ms,
        )
        db.add(check_run)
        db.commit()

        return CheckResult(
            verdict=final_verdict,
            violations=valid_violations,
            warnings=judge_data.warnings,
            conflicts=judge_data.conflicts,
            recalled_records=recalled_refs,
            checked_tokens=len(content.split()),
            latency_ms=latency_ms,
        )

    def _local_heuristic_check(self, content: str, records: list[MemoryRecord]) -> JudgeResponse:
        """Deterministic fallback pattern matcher if LLM is unavailable."""
        violations: list[RawViolation] = []
        for r in records:
            patterns = []
            try:
                patterns = json.loads(r.check_patterns_json or "[]")
            except Exception:
                pass
            for pat in patterns:
                m = re.search(pat, content, re.IGNORECASE)
                if m:
                    excerpt = m.group(0)
                    violations.append(
                        RawViolation(
                            record_id=r.id,
                            severity="high",
                            excerpt=excerpt,
                            explanation=f"Violates policy: {r.statement[:120]}",
                            suggested_fix="Follow established project pattern.",
                        )
                    )
        return JudgeResponse(
            verdict="fail" if violations else "pass",
            violations=violations,
        )
