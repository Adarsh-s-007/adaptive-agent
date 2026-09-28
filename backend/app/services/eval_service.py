"""Labelled evaluation set runner (Blueprint §19-20, §25.4): applied-record precision/recall."""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.governed_models import EvalRun, MemoryRecord
from app.gateways.project_context import get_project
from app.services.audit_service import AuditService
from app.services.brief_service import BriefService
from app.services.seed_service import eval_set
from app.services.serializers import iso


class EvalService:
    def __init__(self, brief_service: BriefService | None = None) -> None:
        self.brief_service = brief_service or BriefService()

    @staticmethod
    def resolve_labels(db: Session, project_id: str, labels: dict[str, str]) -> dict[str, MemoryRecord | None]:
        records = db.query(MemoryRecord).filter(MemoryRecord.project_id == project_id).all()
        resolved: dict[str, MemoryRecord | None] = {}
        for key, needle in labels.items():
            matches = [r for r in records if needle.lower() in r.statement.lower()]
            # Prefer the active version; superseded records still resolve (for must-not labels).
            matches.sort(key=lambda r: (r.status != "active", -r.created_at.timestamp() if r.created_at else 0))
            resolved[key] = matches[0] if matches else None
        return resolved

    async def run(self, db: Session, project_id: str, set_name: str = "default") -> dict[str, Any]:
        get_project(db, project_id)
        data = eval_set(set_name)
        labels = self.resolve_labels(db, project_id, data["records"])
        results = []
        precisions: list[float] = []
        recalls: list[float] = []
        forbidden_hits = 0
        for task in data["tasks"]:
            brief = await self.brief_service.build_brief(db, project_id, task["task"])
            applied_ids = {a.record.id for a in brief.applied}
            key_by_id = {r.id: k for k, r in labels.items() if r}
            expected = {labels[k].id: k for k in task["must_apply"] if labels.get(k) and labels[k].status == "active"}
            missing = [k for k in task["must_apply"] if not labels.get(k) or labels[k].status != "active"]
            forbidden = {labels[k].id: k for k in task["must_not_apply"] if labels.get(k)}
            hits = applied_ids & set(expected)
            precision = len(hits) / len(applied_ids) if applied_ids else (1.0 if not expected else 0.0)
            recall = len(hits) / len(expected) if expected else 1.0
            forbidden_applied = [forbidden[i] for i in applied_ids if i in forbidden]
            if forbidden_applied:
                forbidden_hits += 1
            precisions.append(precision)
            recalls.append(recall)
            results.append(
                {
                    "id": task["id"],
                    "task": task["task"],
                    "applied": [key_by_id.get(i, i[:8]) for i in applied_ids],
                    "expected": list(expected.values()),
                    "missing_labels": missing,
                    "forbidden_applied": forbidden_applied,
                    "precision": round(precision, 3),
                    "recall": round(recall, 3),
                    "brief_status": brief.status,
                    "filter_mode": brief.filter_mode,
                    "recall_ms": brief.recall_ms,
                    "filter_ms": brief.filter_ms,
                }
            )
        settings = get_settings()
        run = EvalRun(
            project_id=project_id,
            set_name=set_name,
            precision=round(statistics.mean(precisions), 3) if precisions else None,
            recall=round(statistics.mean(recalls), 3) if recalls else None,
            forbidden_rate=round(forbidden_hits / len(results), 3) if results else None,
            models_json=json.dumps(
                {
                    "small": settings.llm_model_small if settings.llm_configured else "heuristic-v1",
                    "large": settings.llm_model_large,
                    "hindsight": settings.hindsight_base_url,
                }
            ),
            results_json=json.dumps(results),
        )
        db.add(run)
        AuditService.log(db, project_id, "EVAL", detail={"precision": run.precision, "recall": run.recall})
        db.commit()
        return self.dto(run)

    @staticmethod
    def dto(run: EvalRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "set": run.set_name,
            "precision": run.precision,
            "recall": run.recall,
            "forbidden_rate": run.forbidden_rate,
            "models": json.loads(run.models_json or "{}"),
            "results": json.loads(run.results_json or "[]"),
            "created_at": iso(run.created_at) or datetime.now(timezone.utc).isoformat(),
        }
