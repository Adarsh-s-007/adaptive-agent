# ProjectPulse — Cross-Agent Engineering Memory

**One-line pitch:** Give every coding agent the project decisions it needs from Hindsight before it starts a task.

Coding agents lose useful engineering context between sessions. ProjectPulse retains decisions, conventions, bug fixes, and failed approaches in a bank dedicated to one project. A fresh agent recalls a small, relevant set and answers with the prior decisions in view. The dashboard makes the generic and memory-aware answers easy to compare.

## Architecture

```text
React + Vite dashboard
         |
         v
FastAPI ------ PostgreSQL / Supabase (project metadata and audit timeline)
   |  |
   |  +------ Groq (relevance check and two comparison answers)
   |
   +--------- Hindsight Cloud (isolated project banks, Retain and Recall)
```

See [architecture.md](docs/architecture.md) for the bank boundary and request flow. The dashboard is the screenshot-ready demo surface; add captured screenshots to `docs/screenshots/` after configuring live services.

## Stack

- React 18, TypeScript, Vite
- Python, FastAPI, SQLAlchemy, PostgreSQL or Supabase PostgreSQL
- Hindsight Cloud for durable project memory
- Groq chat completions for task relevance and answers

## What the memory operations do

**Retain:** The API validates a project, builds a stable document ID, and posts the learning to that project's Hindsight bank with a timestamp, project/type tags, and source-agent metadata. It writes a separate audit event to PostgreSQL after Hindsight confirms the operation. Demo seeding uses deterministic document IDs so reruns do not duplicate memory.

**Recall:** The API sends the current task to that project's bank with a strict project tag filter. It requests a compact token budget plus source chunks. Groq selects only the returned facts that materially affect the task, and those selected facts are shown as evidence and placed in the memory-aware prompt. An unrelated task can have zero selected memories.

**Reflect:** Hindsight Reflect is an optional future insight feature. The MVP uses Hindsight Retain and Recall and uses Groq to make the generic versus memory-aware comparison explicit.

Current Hindsight HTTP API: [Retain](https://docs.hindsight.vectorize.io/retain/), [Recall](https://docs.hindsight.vectorize.io/recall/). Groq uses its [chat completions and JSON Object Mode](https://console.groq.com/docs/structured-outputs).

## Run locally

Prerequisites: Python 3.11+, Node 20+, PostgreSQL (or a Supabase connection string), a Hindsight Cloud API key, and a Groq API key.

From the repository root, copy `.env.example` to `.env` and set:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL/Supabase URL, for example `postgresql+psycopg://user:password@localhost:5432/projectpulse` |
| `HINDSIGHT_API_KEY` | Server-side Hindsight Cloud key |
| `HINDSIGHT_BASE_URL` | Defaults to `https://api.hindsight.vectorize.io` |
| `GROQ_API_KEY` | Server-side Groq key |
| `GROQ_MODEL` | Defaults to `llama-3.3-70b-versatile` |
| `CORS_ORIGINS` | Comma-separated frontend origins, default `http://localhost:5173` |

Create the PostgreSQL database named in `DATABASE_URL`. SQLAlchemy creates the four MVP tables on API startup. In one terminal:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. FastAPI documentation is at `http://localhost:8000/docs`. The frontend uses `http://localhost:8000` by default; set `VITE_API_URL` for another API origin. Never put Hindsight or Groq keys in a `VITE_` variable.

For a local API smoke test without PostgreSQL, `DATABASE_URL=sqlite:///./projectpulse.db` is supported. PostgreSQL/Supabase is the intended application database.

## E-commerce demo

Click **Launch E-commerce demo** to create the project/bank and Retain eight realistic lessons: JWT cookie security, payment connection-pool remediation, the task API contract, React Query state ownership, soft-deleted orders, the failed payment rollback, signed product-image uploads, and local cart state. The project dashboard also has a repeatable **Seed demo data** button.

To demonstrate the complete handoff, use **Retain learning** as Agent A, choose the JWT example, then select **Agent B - fresh session** and ask “Build the login screen and authentication flow.” The evidence panel shows which Hindsight facts were used, their source and date. The memory-aware answer should apply the HTTP-only cookie rule and avoid localStorage. See the [90-second demo script](docs/demo-script.md).

## Verify

```bash
cd backend
pip install -r requirements-dev.txt
ruff check app tests
ruff format --check app tests
python -m unittest discover -s tests -v
```

```bash
cd frontend
npm ci
npm run lint
npm test
npm run build
```

The automated tests stub external providers only at the network boundary. They check bank routing, seed idempotency, audit events, request schema, unrelated-task abstention, and the seed → Retain → Agent B comparison UI. To validate live provider calls, configure real keys and run the E-commerce demo in the browser.

## Out of scope

IDE/Claude Code/Antigravity integrations, repository-wide ingestion, live GitHub hooks, autonomous code changes, user login and permissions, and Reflect insights. The API is unauthenticated for this hackathon demo; put access control in front of it before public deployment.
