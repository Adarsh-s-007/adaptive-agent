# ProjectPulse architecture

```text
React SPA (8 screens) ─┐                         ┌─ HindsightGateway ── Hindsight Cloud (one bank per project)
                       ├─ FastAPI routers ─ services ─┤
MCP agents (stdio) ────┘   (validate, delegate)   └─ LLMGateway ─────── Groq / OpenAI-compatible
                                   │
                                   └── SQLAlchemy ── PostgreSQL / SQLite (governance, runs, audit)
```

## Layers

| Layer | Modules | Rule |
| --- | --- | --- |
| Core | `config`, `core/errors`, `core/security`, `core/logging`, `core/context`, `core/ratelimit`, `core/tokens`, `core/taxonomy`, `core/secrets`, `core/memory_conventions` | Settings from env; error envelope; JSON logs with request IDs; ID/tag/metadata conventions |
| Gateways | `gateways/hindsight_gateway.py`, `gateways/llm_gateway.py`, `gateways/project_context.py` | The only code that calls Hindsight or the LLM. Isolation, timeouts, retries, hedged recall, audit events on the `ProjectContext` |
| Services | `project`, `session`, `extraction` (+ `extraction_validator`, `signals`, `transcript_parser`, `heuristics`), `review`, `governed_memory`, `brief`, `generation`, `check`, `compare`, `reflect`, `timeline`, `metrics`, `eval`, `seed`, `audit`, `container` | Business logic; no HTTP; persist audit events with the caller's DB session |
| Jobs | `jobs/retry_worker.py` | Outbox retry every 30 s with exponential backoff (≤ 8 attempts) + startup reconciler |
| API | `api/v1/endpoints.py`, `api/v1/schemas.py`; legacy `api/routes.py` | Routers validate and delegate; request models ignore unknown fields (no client bank IDs) |
| Prompts | `prompts/templates.py`, `prompts/schemas.py` | Versioned prompts next to their Pydantic output schemas |
| MCP | `services/mcp_server.py`, `projectpulse-mcp/server.py` | Governed tools share the dashboard services |

## Data (PostgreSQL / SQLite)

`projects` (bank mapping, bank status, Rulebook cache) · `agent_sessions` + `session_turns` (transcripts, never retained into Hindsight) · `memory_candidates` · `memory_records` (+ `record_evidence`, version chain, `retain_state` outbox) · `task_runs` (frozen recall snapshot, tokens, latencies) · `check_runs` · `comparison_runs` · `audit_events` (every Hindsight/LLM call with latency, isolation blocks) · `rulebook_snapshots` · `eval_runs`. Schema is synced additively at startup (new tables/columns only, never destructive).

## Key flows

- **Memory formation:** import/close session → extract (LLM or labelled heuristic) → validator → relate (Hindsight recall top 5 per candidate) → Inbox → approve → record `pending` → retain → `retained` (failures → `failed` + backoff → worker).
- **Supersession:** create B (supersedes A, "Replaces the decision of …") → A `superseded` + `retag_pending` → Documents API retag → `retained`. Recall excludes A by tag group and by PostgreSQL post-filter.
- **Brief:** zero active records → no recall · recall (hedged) → group by record → status post-filter → applicability (reason per record) → ≤ 5 importance-first → `<project_memory>` block with measured tokens.
- **Compare:** create row → background task → brief once, generate baseline and memory in parallel (separate DB sessions, repeats 1 or 3) → blind checks in parallel → summary + fairness line; SSE streams stage changes.
- **Degradation:** Hindsight unavailable → brief/check/ask `unavailable`, approvals `pending` ("Waiting to sync"), Rulebook from cache, baseline still runs; bank 404 → project `error` with Reprovision.
