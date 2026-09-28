# ProjectPulse architecture

## Layers

| Layer | Location | Rule |
|---|---|---|
| Routers | `backend/app/api/*.py` | Validate and delegate. Paths are relative to `/api/v1`, and every route needs the bearer token except `/health`. |
| Services | `backend/app/services/*.py` | Business logic for one stage of the loop. Raise `AppError`, never `HTTPException`. |
| Gateways | `backend/app/gateways/` | The only code that talks to Hindsight or Groq. Take a `ProjectContext`, never a raw bank id. |
| Core | `backend/app/core/` | Config, errors, security, ids, tokens, audit, memory conventions. |
| DB | `backend/app/db/models.py`, `alembic/` | Ten tables (blueprint §14). Only P1 changes them. |

## Memory loop

Capture → Extract → Review → Retain → Brief → Generate → Check, with Reflect feeding the Rulebook and Ask.

1. **Retain** (P3 `memory_service.create_record`): the record is saved as `pending` and committed, then retained to Hindsight, then marked `retained` or `failed`. The transaction is never held across the provider call.
2. **Supersede** (P3): the new record is retained with a "Replaces the decision of …" line. The old record is retagged `status:superseded` and marked superseded in PostgreSQL. If the retag fails, the old record becomes `retag_pending`, and Brief still excludes it because it post-filters by PostgreSQL status.
3. **Brief** (P5 `brief_service.build_brief`): skipped when there are no active records. Otherwise: recall → group facts by `record_id` → keep active records only → applicability filter (≤5 applied, each with a reason) → injected token count. If the filter fails, the top 3 are used and labelled `unfiltered`. If Hindsight is down, the result is `memory_unavailable`.
4. **Run** (P5 `generation_service.run`): baseline and memory runs use identical prompts except for the `<project_memory>` block. Baseline runs make no Hindsight calls.

## Hindsight document conventions

Defined once in `app/core/memory_conventions.py`:

- `document_id = "mem_<record_uuid>"`
- tags `type:<type>`, `area:<area>`, `status:<status>`, and `confidence:low` when applicable
- metadata values are strings (absent values are empty strings): record_id, project_id, type, area, importance, source_session_id, supersedes, stated_by
- timestamp = `decided_at`

## Isolation

One bank per project, resolved server-side by `gateways/project_context.resolve()`. No endpoint accepts a bank id (tested in `tests/unit/platform`).
