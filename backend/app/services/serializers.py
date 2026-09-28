"""JSON DTO builders shared by the API routers, MCP tools and background jobs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.core.taxonomy import MEMORY_TYPES, normalize_type
from app.db.governed_models import (
    CheckRun,
    ComparisonRun,
    MemoryCandidate,
    MemoryRecord,
    SessionTurn,
    TaskRun,
)
from app.models.entities import AgentSession, Project


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def review_due(record: MemoryRecord) -> bool:
    due = _aware(record.review_due_at)
    return bool(record.status == "active" and due and due <= datetime.now(timezone.utc))


def record_ref(record: MemoryRecord) -> dict[str, Any]:
    """Compact record used in briefs, checks and pills."""
    memory_type = normalize_type(record.type)
    return {
        "id": record.id,
        "pill": record.pill,
        "type": memory_type,
        "title": record.title,
        "statement": record.statement,
        "rationale": record.rationale,
        "area": record.area,
        "applies_to": loads(record.applies_to_json, []),
        "importance": record.importance,
        "status": record.status,
        "confidence_band": record.confidence_band,
        "decided_at": iso(record.decided_at),
        "tentative": bool(record.tentative or record.confidence_band == "low"),
        "review_due": review_due(record),
        "retain_state": record.retain_state,
    }


def record_dto(record: MemoryRecord, *, include_content: bool = False) -> dict[str, Any]:
    memory_type = normalize_type(record.type)
    data = {
        **record_ref(record),
        "project_id": record.project_id,
        "type_label": MEMORY_TYPES[memory_type].label,
        "raw_type": record.type,
        "confidence": record.confidence,
        "stated_by": record.stated_by,
        "source": record.source,
        "tags": loads(record.tags_json, []),
        "metadata": loads(record.metadata_json, {}),
        "hindsight_document_id": record.hindsight_document_id,
        "retry_count": record.retry_count,
        "last_error": record.last_error,
        "supersedes_id": record.supersedes_id,
        "superseded_by_id": record.superseded_by_id,
        # Aliases kept for older clients.
        "supersedes": record.supersedes_id,
        "superseded_by": record.superseded_by_id,
        "candidate_id": record.candidate_id,
        "source_session_id": record.source_session_id,
        "approved_by": record.approved_by,
        "approved_at": iso(record.approved_at),
        "review_due_at": iso(record.review_due_at),
        "retired_at": iso(record.retired_at),
        "retract_reason": record.retract_reason,
        "check_patterns": loads(record.check_patterns_json, []),
        "times_applied": record.times_applied or 0,
        "times_violated": record.times_violated or 0,
        "evidence_count": len(record.evidence),
        "created_at": iso(record.created_at),
        "updated_at": iso(record.updated_at),
    }
    if include_content:
        data["retained_content"] = record.retained_content
        data["evidence"] = [
            {
                "id": ev.id,
                "quote": ev.quote,
                "speaker": ev.speaker,
                "turn_index": ev.turn_index,
                "source_session_id": ev.source_session_id,
                "created_at": iso(ev.created_at),
            }
            for ev in record.evidence
        ]
    return data


def candidate_dto(c: MemoryCandidate, related: MemoryRecord | None = None) -> dict[str, Any]:
    confidence = float(c.confidence or 0.0)
    band = "high" if confidence >= 0.75 else "medium" if confidence >= 0.4 else "low"
    return {
        "id": c.id,
        "project_id": c.project_id,
        "session_id": c.session_id,
        "type": normalize_type(c.type),
        "title": c.title,
        "statement": c.statement,
        "rationale": c.rationale,
        "area": c.area,
        "applies_to": loads(c.applies_to_json, []),
        "importance": c.importance or 2,
        "stated_by": c.stated_by or "human",
        "evidence_quote": c.evidence_quote,
        "evidence_turn_ids": loads(c.evidence_turn_ids_json, []),
        "status": "auto_rejected" if c.status == "filtered" else c.status,
        "filter_reason": c.filter_reason,
        "relation": "new" if c.relation in (None, "", "unrelated") else c.relation,
        "related_record_id": c.related_record_id,
        "related_record": record_ref(related) if related else None,
        "relation_reason": c.relation_reason,
        "confidence": confidence,
        "confidence_band": band,
        "flagged": bool(c.flagged),
        "flags": loads(c.flags_json, []),
        "extractor_model": c.extractor_model,
        "record_id": c.record_id,
        "reviewed_by": c.reviewed_by,
        "reviewed_at": iso(c.reviewed_at),
        "reject_reason": c.reject_reason,
        "created_at": iso(c.created_at),
    }


def turn_dto(t: SessionTurn) -> dict[str, Any]:
    return {
        "id": t.id,
        "seq": t.turn_index,
        "turn_index": t.turn_index,
        "role": t.role,
        "speaker": t.speaker,
        "content": t.content,
        "run_id": t.run_id,
        "meta": loads(t.meta_json, {}),
        "created_at": iso(t.created_at),
    }


def session_dto(s: AgentSession, *, turns: list[SessionTurn] | None = None) -> dict[str, Any]:
    data = {
        "id": s.id,
        "project_id": s.project_id,
        "title": s.title or s.task,
        "developer": s.developer,
        "agent_label": s.agent_label or s.agent_name,
        "source": s.source or "legacy",
        "status": s.status or "closed",
        "occurred_at": iso(s.occurred_at or s.created_at),
        "started_at": iso(s.created_at),
        "ended_at": iso(s.ended_at),
        "extraction_error": s.extraction_error,
        "extraction_stats": loads(s.extraction_stats_json, {}),
        "turn_count": s.turn_count or (len(turns) if turns is not None else 0),
        "created_at": iso(s.created_at),
    }
    if turns is not None:
        data["turns"] = [turn_dto(t) for t in turns]
    return data


def run_dto(run: TaskRun) -> dict[str, Any]:
    brief = loads(run.brief_snapshot_json, None)
    return {
        "id": run.id,
        "project_id": run.project_id,
        "session_id": run.session_id,
        "comparison_id": run.comparison_id,
        "repeat_index": run.repeat_index or 0,
        "mode": run.mode,
        "task": run.task,
        "status": run.status or "ok",
        "error": loads(run.error_json, None),
        "model": run.model,
        "temperature": run.temperature,
        "output": {
            "summary": run.summary,
            "files": loads(run.output_files_json, []),
            "notes": loads(run.output_notes_json, []),
            "followed_record_ids": loads(run.followed_record_ids_json, []),
        },
        "brief": brief,
        "usage": {
            "prompt_tokens": run.prompt_tokens,
            "completion_tokens": run.completion_tokens,
        },
        "injected_tokens": run.injected_tokens or 0,
        "recall_ms": run.recall_ms or 0,
        "filter_ms": run.filter_ms or 0,
        "llm_ms": run.llm_ms or 0,
        "latency_ms": run.latency_ms,
        "created_at": iso(run.created_at),
    }


def check_dto(check: CheckRun) -> dict[str, Any]:
    verdict = {"pass": "compliant", "fail": "violations"}.get(check.verdict, check.verdict)
    return {
        "id": check.id,
        "project_id": check.project_id,
        "run_id": check.run_id,
        "verdict": verdict,
        "judge_model": check.judge_model,
        "violations": loads(check.violations_json, []),
        "warnings": loads(check.warnings_json, []),
        "conflicts": loads(check.conflicts_json, []),
        "recalled_record_ids": loads(check.recalled_record_ids_json, []),
        "checked_tokens": check.checked_tokens,
        "latency_ms": check.latency_ms,
        "content_preview": check.content_preview,
        "created_at": iso(check.created_at),
    }


def comparison_dto(c: ComparisonRun) -> dict[str, Any]:
    return {
        "id": c.id,
        "project_id": c.project_id,
        "task": c.task,
        "repeats": c.repeats or 1,
        "status": c.status,
        "stage": c.stage,
        "error": loads(c.error_json, None),
        "baseline_run_ids": loads(c.baseline_run_ids_json, []),
        "memory_run_ids": loads(c.memory_run_ids_json, []),
        "violations_baseline": c.violations_baseline,
        "violations_memory": c.violations_memory,
        "violation_delta": c.violation_delta,
        "applied_count": c.applied_count,
        "injected_tokens": c.injected_tokens,
        "summary": loads(c.summary_json, {}),
        "fairness": loads(c.fairness_json, {}),
        "created_at": iso(c.created_at),
        "completed_at": iso(c.completed_at),
    }


def project_dto(p: Project, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    legacy_demo = (p.hindsight_bank_id or "").startswith("demo-")
    return {
        "id": p.id,
        "name": p.name,
        "slug": p.slug,
        "description": p.description,
        "tech_stack": p.tech_stack or "",
        "areas": loads(p.areas_json, []),
        "bank_id": p.hindsight_bank_id,
        "hindsight_bank_id": p.hindsight_bank_id,
        "bank_status": p.bank_status or "ready",
        "bank_error": p.bank_error,
        "memory_mode": "demo" if legacy_demo else "hindsight",
        "rulebook_cached_at": iso(p.rulebook_cached_at),
        "provisioned_at": iso(p.provisioned_at),
        "created_at": iso(p.created_at),
        "stats": stats or {},
    }
