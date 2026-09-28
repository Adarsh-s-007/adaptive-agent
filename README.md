# ProjectPulse

Reviewed engineering memory for AI coding agents, powered by Hindsight. ProjectPulse turns what one coding session learned into governed project memory, briefs the next session with only the decisions that apply, and checks that session's output against them.

> Status: Phase 0 skeleton. See `OWNERSHIP.md` for who builds what. The old MVP is preserved at the git tag `legacy-mvp`.

## Architecture

```text
React SPA (Vite, Tailwind, TanStack Query)
        |  Authorization: Bearer APP_ACCESS_TOKEN
        v
FastAPI /api/v1  routers -> services -> gateways / repositories
        |                          |                |
        |                          |                +-- PostgreSQL: governance, runs, audit
        |                          +-- hindsight_gateway -> Hindsight Cloud (one bank per project)
        +-- llm_gateway -> Groq (gpt-oss-120b generate/judge, gpt-oss-20b extract/relate/applicability)
```

- **Hindsight** owns all searchable memory, recall, observations, the Rulebook mental model and reflect.
- **PostgreSQL** owns projects and bank mapping, sessions, candidates, record lifecycle, runs, checks and the audit log. It never does agent-facing retrieval.
- Only `app/gateways/hindsight_gateway.py` talks to Hindsight, and only `app/gateways/llm_gateway.py` talks to Groq. CI enforces both.

## Run locally

Prerequisites: Python 3.12+, Node 20+, Docker (for Postgres).

```bash
cp .env.example .env        # fill in APP_ACCESS_TOKEN, HINDSIGHT_API_KEY, GROQ_API_KEY
docker compose up -d postgres
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev                 # http://localhost:5173, enter APP_ACCESS_TOKEN at the gate
```

Seed the demo projects (needs the projects API):

```bash
PROJECTPULSE_API_URL=http://localhost:8000 APP_ACCESS_TOKEN=... python scripts/seed.py
```

## Verify

```bash
cd backend && ruff check app tests alembic ../scripts && ruff format --check app tests alembic && pytest -q
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

Live tests that spend Hindsight/Groq credit are marked `live` and skipped by default: `pytest -m live`.

## Team workflow

1. `git config pull.rebase true && git config core.hooksPath scripts/dev/hooks`
2. `export PP_OWNER=P1` (your id). The pre-commit hook blocks files you don't own.
3. Commit small, `git add` explicit paths, `git pull --rebase`, run your checks, `git push`. Rejected push: pull --rebase and push again.
4. Need a change in someone else's file, a new dependency or a DB column? Open a `contract:` issue for the owner.

## License

MIT
