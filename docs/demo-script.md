# ProjectPulse 90-second MCP-first demo

Before judges arrive, start the API and frontend, open `http://localhost:5176`, and keep **Agent activity** ready. If no Hindsight key is configured, say clearly that the demonstration uses **Demo mode - local sample memory**. The MCP tool call remains real; only its memory backend is local.

**0-15 seconds - The problem.** "A new coding-agent session loses project decisions. ProjectPulse is a project-scoped MCP memory layer, not a generic chatbot." Show the landing screen and click **Launch E-commerce MCP demo**.

**15-30 seconds - Agent A's learning.** Open **Memory timeline**. Point at the JWT security rule: refresh tokens must use HTTP-only, Secure cookies; LocalStorage is forbidden. Show type, tags, source Agent A, session, timestamp, and storage origin. Mention the other realistic API, order, payment, and frontend memories.

**30-55 seconds - A truly fresh Agent B session.** Open **Agent activity** and click **Run fresh Agent B MCP demo**. This invokes the registered `recall_project_memory` tool through the official MCP Client, with task "Implement login and refresh-token flow for this project." It creates a new session and a recall audit event.

**55-75 seconds - The proof.** In the chronological activity stream, show "Fresh Agent B session started", user task, `projectpulse.recall_project_memory`, exact recalled JWT evidence, and the local sample approach that uses HttpOnly/Secure cookies and avoids LocalStorage. Point to **Why this answer is project-aware**. State that the sample result is *not* an external coding agent.

**75-90 seconds - Real integration path.** Open **MCP setup**, choose Claude Code or GitHub Copilot, show the generated client JSON and project instructions. Explain that compatible agents can call the three tools before/after coding, but MCP does not invoke tools automatically. With Hindsight configured, new projects use real isolated Hindsight banks.

For an independent stdio transport proof, run from the repository root:

```bash
backend/.venv/bin/python projectpulse-mcp/demo_cli.py
```

This launches the MCP server as a child process, prints the actual recalled memory, and logs a labelled sample result. Refresh the dashboard activity tab. See [README.md](../README.md) for setup and demo-mode limitations.
