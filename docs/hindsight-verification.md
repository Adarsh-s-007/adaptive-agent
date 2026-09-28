# Hindsight verification record (Blueprint §15.9)

Verified live against **Hindsight Cloud API 0.10.1** (`https://api.hindsight.vectorize.io`, OpenAPI spec pulled on 2026-09-29) on throwaway banks `pp_probe_*`, all deleted afterwards.

| Item | Result | What ProjectPulse does |
| --- | --- | --- |
| Base URL + bearer auth | `GET /v1/default/banks?limit=1` → 200 | Health probe with a 3 s timeout |
| `PUT /banks/{id}` | 200; `name`, `reflect_mission` accepted (mission/disposition fields on this route are deprecated) | Create bank, then configure via `PATCH /config` |
| `PATCH /banks/{id}/config` `{updates:{…}}` | 200; `retain_extraction_mode: verbatim`, missions, dispositions, `enable_observations` all applied | Sent on provisioning |
| Memory Defense (`memory_defense.sensitive_data`) | **400 `detectors_not_entitled`** on this plan | Gateway retries config without it; ProjectPulse validator redaction always applies |
| Directives `POST /directives` | 200 | 3 guardrails, idempotent by name |
| Mental model `POST /mental-models` with `id: rulebook`, `trigger.refresh_after_consolidation` | 200 + `operation_id`; content `"Generating content..."` until the first refresh completes | Rulebook shows a *generating* state; `trigger.tag_groups` excludes superseded/retracted |
| Mental model refresh / get | refresh queued (200); content arrives ~10–15 s later | Overview polls while generating; content cached with timestamp |
| Mental model history | `[]` after one refresh | ProjectPulse stores its own `rulebook_snapshots` for *What changed* |
| Sync retain with `document_id`, `timestamp`, `context`, `tags`, `metadata`, `entities` | 200 in ~2.6 s; document metadata and retain params stored | One record = one document `mem_<record_id>` |
| Recall with `tag_groups` (`project` leaf AND `not status:superseded/retracted`) | Works — superseded documents excluded | Used for Brief, Check and Relate |
| Document retag `PATCH /documents/{id}` `{tags}` | 200 `{success:true}`; tags replaced, derived units follow | Supersede/retract step 2 |
| Recall of a missing bank | 404 `Bank '…' not found` | `BankMissing` → project `error`, Reprovision offered |
| Reflect with `include.facts` and `tag_groups` | 200; `based_on.memories` are memory-unit IDs (no `document_id`), `based_on.directives` listed | Units resolved via `GET /memories/{id}` → `document_id` / metadata → record |
| Observations | Returned as `type: observation` with the source documents' tags; `source_fact_ids` only with `include.source_facts` | Requested with `source_facts`; mapped back to records |

## Reliability finding: empty recall responses

Identical recalls against an unchanged bank returned **0 results ~40% of the time** (40 calls over 100 s: 24 non-empty, 16 empty; empties are fast, ~370 ms), independent of filters. `HindsightGateway.recall_detailed` therefore, when the bank is known to hold active records, fires **two hedged requests per round for up to three rounds** and records `attempts` in the `RECALL` audit event. With independent failures the chance of a false "no memory" drops to well under 1%.

## End-to-end run (live)

Seed ApexCart (13 records, async retain) → Brief (recall ~1 s) → extract S-104 (2 candidates, 6 filtered) → approve both (retained) → extract S-131 (supersedes + duplicate) → LedgerLite brief returns only LedgerLite's rules → Check flags `new PrismaClient()`, `localStorage.setItem('token', …)`, PII logging → Ask cites the Redis failed-approach record → Rulebook generated → isolation counter 0.
