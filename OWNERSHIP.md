# File ownership

Each path has exactly one owner. Only the owner commits to it; everyone else imports.
Need a change in someone else's file? Open an issue titled `contract: ...` and ask them.
`scripts/dev/hooks/pre-commit` blocks commits outside your paths (set `PP_OWNER=P1..P6`).

The machine-readable list is `scripts/dev/ownership.txt` (first matching prefix wins).

| Owner | Area | Paths |
|---|---|---|
| P1 | Platform, shell, delivery | `backend/app/main.py`, `backend/app/core/`, `backend/app/db/models.py`, `backend/app/db/session.py`, `backend/alembic*`, `backend/pyproject.toml`, `backend/app/api/router.py`, `backend/app/api/health.py`, `backend/app/schemas/common.py`, `backend/tests/conftest.py`, `backend/tests/unit/platform/`, `frontend/` root config, `frontend/src/{main.tsx,app,api,components,styles}`, `frontend/src/features/settings/`*, root files, `.github/workflows/`, `docs/architecture.md` |
| P2 | Hindsight, projects, Reflect, MCP | `backend/app/gateways/hindsight_gateway.py`, `backend/app/gateways/project_context.py`, `services/{project,reflect}_service.py`, `api/{projects,reflect,admin_hindsight}.py`, `schemas/{projects,reflect}.py`, `tests/fakes/fake_hindsight.py`, `tests/*/{hindsight,projects,reflect,isolation}/`, `projectpulse-mcp/`, `.mcp.json`, `CLAUDE.md`, `.github/copilot-instructions.md`, `frontend/src/features/{projects,overview}/` |
| P3 | Records, timeline, seed | `services/{memory_service,record_template,timeline_service,metrics_service}.py`, `app/jobs/`, `api/{memories,timeline,metrics,admin_seed}.py`, `schemas/memories.py`, `tests/*/memory/`, `seed/apexcart/{project,records}.yaml`, `seed/ledgerlite/`, `scripts/seed.py`, `frontend/src/features/memory/` |
| P4 | Capture, extraction, review | `services/{session_service,transcript_parser,signals,extraction_service,extraction_validator,review_service}.py`, `api/{sessions,candidates}.py`, `schemas/{sessions,candidates}.py`, `prompts/{extract,relate}.md`, `prompts/schemas/extraction.py`, `tests/*/{sessions,extraction,review}/`, `seed/apexcart/transcripts/`, `frontend/src/features/inbox/` |
| P5 | Brief, generation, eval | `gateways/llm_gateway.py`, `services/{brief_service,prompt_assembler,generation_service,eval_service}.py`, `api/{brief,runs,workspace,eval}.py`, `schemas/{brief,runs}.py`, `prompts/{generate,applicability}.md`, `prompts/schemas/{generation,applicability}.py`, `tests/fakes/fake_llm.py`, `tests/*/brief/`, `seed/eval_tasks.yaml`, `frontend/src/features/workspace/` |
| P6 | Check, compare, demo | `services/{check_service,compare_service}.py`, `api/{check,compare}.py`, `schemas/{check,compare}.py`, `prompts/judge.md`, `prompts/schemas/check.py`, `tests/*/{check,compare}/`, `seed/demo_tasks.yaml`, `scripts/demo_loop.py`, `docs/demo-script.md`, `frontend/src/features/{compare,check-ask}/`, `frontend/e2e/` |

\* Settings screen moved to P1 after the scope cut.

## Table write ownership

Any code may read any table. Only the owner writes it; others call the owner's service.

| Table | Writer | Others call |
|---|---|---|
| projects | P2 | `project_context.resolve()` |
| agent_sessions, session_turns, memory_candidates | P4 | `session_service.append_turns()` |
| memory_records, record_evidence | P3 | `memory_service.create_record/supersede/retract/add_evidence` |
| task_runs | P5 | `generation_service.run()` |
| check_runs, comparison_runs | P6 | — |
| memory_events | everyone via `core.audit.record_event()` | — |

## Rules

1. Only P2 calls Hindsight. Only P5 calls Groq.
2. Only P1 edits `db/models.py`, writes Alembic migrations, or changes `pyproject.toml` and `package.json` or their lockfiles.
3. Services raise `AppError`, never `HTTPException`.
4. `git add` explicit paths only. `git pull --rebase` before every push. Never force-push `main`.
