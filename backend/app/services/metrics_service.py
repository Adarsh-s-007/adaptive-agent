"""Section 20 metrics: every number is computed from stored runs; nothing is claimed."""

from __future__ import annotations

import json
import statistics
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.governed_models import (
    AuditEvent,
    CheckRun,
    ComparisonRun,
    EvalRun,
    MemoryCandidate,
    MemoryRecord,
    TaskRun,
)
from app.gateways.hindsight_gateway import HindsightGateway
from app.services.audit_service import AuditService
from app.services.serializers import iso, loads, record_ref


def _percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct * (len(ordered) - 1))))
    return int(ordered[index])


class MetricsService:
    def __init__(self, gateway: HindsightGateway | None = None) -> None:
        self.gateway = gateway

    async def get_project_metrics(self, db: Session, project_id: str) -> dict[str, Any]:
        records = db.scalars(select(MemoryRecord).where(MemoryRecord.project_id == project_id)).all()
        active = [r for r in records if r.status == "active"]
        by_type: dict[str, int] = {}
        for r in active:
            by_type[r.type] = by_type.get(r.type, 0) + 1

        comparisons = db.scalars(
            select(ComparisonRun)
            .where(ComparisonRun.project_id == project_id, ComparisonRun.status == "completed")
            .order_by(ComparisonRun.created_at.desc())
            .limit(10)
        ).all()
        deltas = [loads(c.summary_json, {}).get("violation_delta", c.violation_delta) for c in comparisons]

        recall_events = db.scalars(
            select(AuditEvent)
            .where(AuditEvent.project_id == project_id, AuditEvent.event_type == "RECALL", AuditEvent.status == "ok")
            .order_by(AuditEvent.created_at.desc())
            .limit(200)
        ).all()
        recall_latencies = [e.latency_ms for e in recall_events if e.latency_ms is not None]

        memory_runs = db.scalars(
            select(TaskRun)
            .where(TaskRun.project_id == project_id, TaskRun.mode == "memory", TaskRun.status == "ok")
            .order_by(TaskRun.created_at.desc())
            .limit(100)
        ).all()
        brief_latencies = [(r.recall_ms or 0) + (r.filter_ms or 0) for r in memory_runs]
        injected = [r.injected_tokens or 0 for r in memory_runs]
        utilisation = []
        for run in memory_runs:
            brief = loads(run.brief_snapshot_json, {}) or {}
            applied = len(brief.get("applied") or [])
            if applied:
                utilisation.append(len(loads(run.followed_record_ids_json, [])) / applied)

        cand_rows = db.execute(
            select(MemoryCandidate.status, func.count())
            .where(MemoryCandidate.project_id == project_id)
            .group_by(MemoryCandidate.status)
        ).all()
        extraction = {"proposed": 0, "pending": 0, "approved": 0, "rejected": 0, "auto_rejected": 0}
        for status, count in cand_rows:
            key = "auto_rejected" if status == "filtered" else status
            extraction[key] = extraction.get(key, 0) + int(count)
        extraction["proposed"] = sum(v for k, v in extraction.items() if k != "proposed")

        checks = db.scalars(select(CheckRun).where(CheckRun.project_id == project_id)).all()
        latest_eval = db.scalar(
            select(EvalRun).where(EvalRun.project_id == project_id).order_by(EvalRun.created_at.desc()).limit(1)
        )
        most_applied = sorted(active, key=lambda r: -(r.times_applied or 0))[:8]

        return {
            "records": {
                "total": len(records),
                "active": len(active),
                "superseded": sum(1 for r in records if r.status == "superseded"),
                "retracted": sum(1 for r in records if r.status == "retracted"),
                "by_type": by_type,
                "unsynced": sum(1 for r in records if r.retain_state != "retained"),
                "review_due": sum(1 for r in active if record_ref(r)["review_due"]),
                "tentative": sum(1 for r in active if r.confidence_band == "low"),
            },
            "violation_delta": {
                "last_10": [
                    {
                        "comparison_id": c.id,
                        "task": c.task[:120],
                        "baseline": loads(c.summary_json, {}).get("mean_violations_baseline", c.violations_baseline),
                        "memory": loads(c.summary_json, {}).get("mean_violations_memory", c.violations_memory),
                        "delta": d,
                        "created_at": iso(c.created_at),
                    }
                    for c, d in zip(comparisons, deltas)
                ],
                "median": statistics.median(deltas) if deltas else None,
            },
            "latency": {
                "recall_p50_ms": _percentile(recall_latencies, 0.5),
                "recall_p95_ms": _percentile(recall_latencies, 0.95),
                "brief_p50_ms": _percentile(brief_latencies, 0.5),
                "brief_p95_ms": _percentile(brief_latencies, 0.95),
                "samples": len(recall_latencies),
            },
            "tokens": {
                "injected_avg": round(statistics.mean(injected)) if injected else None,
                "memory_runs": len(memory_runs),
            },
            "memory_utilisation": round(statistics.mean(utilisation), 2) if utilisation else None,
            "extraction_yield": extraction,
            "checks": {
                "total": len(checks),
                "with_violations": sum(1 for c in checks if c.verdict in ("violations", "fail")),
                "violations_found": sum(len(json.loads(c.violations_json or "[]")) for c in checks),
            },
            "application": [
                {**record_ref(r), "times_applied": r.times_applied or 0, "times_violated": r.times_violated or 0}
                for r in most_applied
            ],
            "isolation_violations_blocked": AuditService.isolation_violations(db, project_id),
            "eval": (
                {
                    "id": latest_eval.id,
                    "precision": latest_eval.precision,
                    "recall": latest_eval.recall,
                    "forbidden_rate": latest_eval.forbidden_rate,
                    "created_at": iso(latest_eval.created_at),
                    "models": loads(latest_eval.models_json, {}),
                }
                if latest_eval
                else None
            ),
        }
