# ProjectPulse - project-scoped MCP memory for coding agents

**Pitch:** A coding agent can recall the engineering decisions relevant to its next task, even in a fresh session. ProjectPulse is an MCP memory server powered by Hindsight, with a companion dashboard for inspecting memory and agent activity.

The primary product is `projectpulse-mcp`. The dashboard is an evidence viewer and admin surface, not a coding agent. The included local demo makes a real MCP tool call; its sample coding result is explicitly labelled and is not Claude Code or Copilot.

## Architecture

```text
Claude Code / Copilot / MCP CLI
          |
          | stdio MCP: recall_project_memory, retain_project_memory,
          |            list_project_memories
          v
projectpulse-mcp --> project_memory_service --> Hindsight Cloud
                             |                     one isolated bank/project
                             +--> PostgreSQL/Supabase
                                  project mapping, sessions, audit activity
                             +--> local demo memory (only for demo-mode projects)

React dashboard --> FastAPI --> same shared services and audit database
```

See [architecture.md](docs/architecture.md). No unrestricted database access is given to an LLM.

## What is real, and what is demo mode?

With `HINDSIGHT_API_KEY` configured, new projects receive Hindsight banks. Retain posts durable facts to that bank. Recall asks only that bank, with a strict project tag. List reads Hindsight memory units from that bank. The dashboard displays provider-backed evidence and local audit records.

Without the key, new projects use **Demo mode - local sample memory**. The five primary E-commerce facts plus three supporting facts are stored in a project-scoped local demo table. This mode is visibly labelled throughout the UI and MCP responses; it does **not** pretend to be Hindsight. Its relevance matching is simple keyword overlap, not Hindsight retrieval. Existing demo-mode projects stay in demo mode if a key is added later; create a new project/database for a real-bank demo.

Groq is optional for the MCP-first flow. The original `/agent-answer` comparison endpoint remains for compatibility and requires Groq and Hindsight; the dashboard now focuses on actual MCP activity.

## Set up locally

Requirements: Python 3.11+, Node 20+, and optionally PostgreSQL/Supabase, a Hindsight Cloud key, and a Groq key. The no-key local demo uses SQLite. Never commit `.env`.

```bash
cp .env.example .env
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r ../projectpulse-mcp/requirements.txt
uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev -- --port 5176
```

Open [http://localhost:5176](http://localhost:5176). Set `CORS_ORIGINS=http://localhost:5176` in `.env` if you change ports. The frontend calls `http://localhost:8000` by default; set `VITE_API_URL` only if the backend runs elsewhere.

Environment variables:

| Name | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLite for a local sample or `postgresql+psycopg://...` / Supabase PostgreSQL for normal data |
| `HINDSIGHT_API_KEY` | Server-side Hindsight Cloud key; blank enables clearly labelled demo mode for new projects |
| `HINDSIGHT_BASE_URL` | Defaults to `https://api.hindsight.vectorize.io` |
| `GROQ_API_KEY` | Optional for legacy comparison answers; not used by MCP tools |
| `GROQ_MODEL` | Model for legacy comparison answers |
| `CORS_ORIGINS` | Comma-separated allowed dashboard origins |

PostgreSQL/Supabase is the intended application database. SQLAlchemy creates the MVP tables on startup. For a real project, set `DATABASE_URL` to PostgreSQL/Supabase and `HINDSIGHT_API_KEY` before creating it. SQLite relative paths resolve against the repository root so API and stdio MCP processes share one demo database.

## Connect a coding agent

The included [project-scoped Claude configuration](.mcp.json) uses the repo's `backend/.venv/bin/python` executable and [MCP server](projectpulse-mcp/server.py). Run Claude Code from this repository and approve the project MCP server when prompted. For another coding repository, open the dashboard's **MCP setup** tab, select Claude Code or GitHub Copilot, copy the appropriate JSON and replace `/absolute/path/to/ProjectPulse` with this checkout's absolute path. Use a WSL workspace when using the shown Unix Python path.

- Claude Code: save the JSON as `.mcp.json` in the coding repository; save the generated instructions as `CLAUDE.md`.
- GitHub Copilot in VS Code: save the JSON as `.vscode/mcp.json`; save the generated instructions as `.github/copilot-instructions.md`. Use Agent mode and confirm that the three ProjectPulse tools are available.

The project UUID is displayed in **MCP setup** and must be supplied in every tool call. Tool availability alone does not trigger calls: the instructions tell the agent to recall before coding and retain only durable, non-secret learning afterward. The three tools are:

| Tool | Input | Effect |
| --- | --- | --- |
| `recall_project_memory` | `project_id`, `task_description`, optional `top_k` | Returns task-relevant memories and logs the session/tool call |
| `retain_project_memory` | `project_id`, `content`, `memory_type`, `tags`, optional `source_agent`/`session_id` | Retains a fact in that project's bank and logs provenance |
| `list_project_memories` | `project_id`, optional `memory_type`/`tag` | Inspects only that project's memories |

Allowed types: `architecture_decision`, `security_rule`, `api_contract`, `incident_fix`, `coding_convention`. The server rejects obvious credential patterns; agents must still avoid personal or sensitive information. The hackathon API has no user authentication, so do not expose it publicly without access control.

The MCP server is a stdio child process launched by a client. To inspect its tools using the official MCP Inspector, install the optional CLI extra and run `mcp dev projectpulse-mcp/server.py`; or use the included true-stdio CLI path below.

## E-commerce demo

Click **Launch E-commerce MCP demo**. In **Memory timeline**, inspect the JWT cookie rule, task API contract, order soft-delete rule, payment-pool fix, and React Query convention. The seed also includes a failed rollback, signed image uploads, and cart state.

Click **Run fresh Agent B MCP demo**. The backend uses the official MCP client to invoke the registered `recall_project_memory` tool. **Agent activity** then shows the fresh session, task, actual tool call, exact JWT evidence, and a clearly labelled local sample code approach that uses HttpOnly/Secure cookies and avoids LocalStorage. The sample result is not an external coding agent.

For a separate stdio-process verification:

```bash
backend/.venv/bin/python projectpulse-mcp/demo_cli.py
```

Run that from the repository root after seeding. It starts the MCP server over stdio, makes the real tool call, prints evidence, and logs the labelled sample result. Pass `--project-id UUID` for another project. Refresh **Agent activity** in the dashboard to see it.

See the exact [90-second demo script](docs/demo-script.md).

## Verify

```bash
cd backend
pip install -r requirements-dev.txt
ruff check app tests ../projectpulse-mcp
ruff format --check app tests ../projectpulse-mcp
python -m unittest discover -s tests -v
```

```bash
cd frontend
npm run lint
npm test
npm run build
```

Tests use provider stubs for Hindsight and Groq. They exercise project isolation, provider payload shape, retention, seeding, MCP tool audit, and the dashboard. A live Hindsight account/credentials are required to verify cloud Retain/Recall/List; none are bundled.

## Intentionally out of scope

Automatic tool invocation without agent instructions, autonomous repository edits by the dashboard, repository ingestion, hosted multi-user authentication, production-grade authorization, and Hindsight Reflect insights. The dashboard does not impersonate Claude Code, Copilot, or another coding agent.

Official integration references: [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), [Claude Code MCP](https://code.claude.com/docs/en/mcp), [VS Code MCP configuration](https://code.visualstudio.com/docs/agent-customization/mcp-servers), [Hindsight Retain](https://docs.hindsight.vectorize.io/retain/), [Recall](https://docs.hindsight.vectorize.io/recall/), and [List memories](https://docs.hindsight.vectorize.io/api-reference/list-memories/).

### Enable real Hindsight Cloud memory

Create a repository-root .env file from .env.example, then set only the server-side value below. Do not add it to the frontend environment, paste it into chat, or commit it.

    HINDSIGHT_API_KEY=hsk_your_key_here

Restart the backend and open http://localhost:8000/health/hindsight. A successful response has status connected; this performs a read-only provider check and does not retain any memory. Then create a new project from the dashboard. Its bank is created in Hindsight Cloud, and Retain, Recall, and List use that bank only. Existing demo-prefixed projects intentionally remain local demo projects.
