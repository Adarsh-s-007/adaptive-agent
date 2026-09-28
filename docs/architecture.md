# ProjectPulse architecture

```text
React + TypeScript dashboard
          |
          v
FastAPI project routes ---- PostgreSQL / Supabase
          |                  projects, sessions, audit events, scenarios
          |
          +---- Hindsight Cloud: one bank per project
          |       PUT bank -> Retain -> task-scoped Recall
          |
          +---- Groq: relevance check -> generic answer -> memory answer
```

Project creation assigns a unique Hindsight bank ID before saving the project. Retain writes engineering learning to that bank with a stable document ID, project/type tags, source-agent metadata, and a timestamp. The database keeps a local audit event and reference; Hindsight owns the searchable long-term memory.

Recall uses the project's stored bank ID and a strict project tag filter. The request uses the current Hindsight Cloud `max_tokens` and nested `include.chunks` fields. Hindsight returns ranked facts and source chunks. A small Groq JSON response then selects only facts that materially affect the current task; it can select none. Only those facts enter the memory-aware answer prompt.

The generic Groq prompt receives the task without recalled memories. Each call to the agent-answer endpoint creates a new agent session and a recall event. A second project has a different bank and cannot search the E-commerce bank through these routes.

The API does not pass database credentials or unrestricted database access to Groq. Authentication and user permissions are outside this hackathon MVP, so deploy the API behind access control if it is made public.
