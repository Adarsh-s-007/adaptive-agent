# ProjectPulse MCP-first architecture

```text
Coding agent (Claude Code / Copilot / MCP CLI)
  -> MCP stdio server: three focused tools
  -> project_memory_service
      -> project_id lookup in PostgreSQL/Supabase
      -> Hindsight Cloud bank for that project (real mode)
      -> demo_memories table for that project (explicit demo mode)
      -> audit_event_service -> sessions, memory_events, agent_activity
  -> coding agent continues with only retrieved facts

React dashboard -> FastAPI -> same project_memory_service + audit database
```

The MCP stdio entry point is `projectpulse-mcp/server.py`. The registered tools live in `backend/app/services/mcp_server.py` so the local in-memory MCP demo and the separate stdio process use identical tool definitions. The API never handles raw MCP transport messages.

## Project isolation

`projects.hindsight_bank_id` is the only bank chosen for a given project UUID. In real mode, retain and recall include the immutable `project:{uuid}` tag; recall uses a strict tag match in that bank. List uses the same bank and project tag. A caller cannot supply a bank ID or override the project tag. Session IDs are checked against the selected project. Demo mode uses a separate, clearly prefixed bank mapping and queries `demo_memories` by project ID; it never calls Hindsight.

Real Hindsight memory is not reconstructed from `memory_events`. That table is an audit trail, while Hindsight owns the long-term searchable memory. The local demo table is used only for projects explicitly created without credentials and is not presented as Hindsight.

## Call flow

1. A new project creates a Hindsight bank if a key is configured; otherwise it receives a `demo-` bank mapping.
2. `retain_project_memory` validates type, tags, source/session, and obvious credential patterns. It sends the fact to Hindsight Retain or local demo storage, then writes a retained event and activity audit.
3. `recall_project_memory` validates the project, retrieves only task-relevant facts, creates a fresh agent session, and writes task/tool/evidence audit entries. It returns memory ID, content, type, tags, source/session, timestamp, and origin.
4. `list_project_memories` reads Hindsight's bank-scoped memory-unit list endpoint or the local demo table, with optional type/tag filters.
5. The dashboard reads the memory list, timeline, and activity. Its judge-facing button uses the official MCP Client against the same registered server object; `demo_cli.py` proves the separate stdio transport too.

The local sample code result after the demo recall is deterministic and labelled. It is not an external agent output. The old Groq comparison route remains available but is not part of the MCP-first path.

## Security and limits

Secrets stay in backend environment variables. The frontend receives no provider key. MCP tools require a project UUID and cannot choose arbitrary banks. The API is unauthenticated for the hackathon and must be protected before public deployment. The list endpoint currently shows up to 100 recent memory units; add pagination for larger projects. SQLAlchemy creates tables at startup, but production deployments should add migrations.
