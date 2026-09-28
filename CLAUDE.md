# ProjectPulse agent instructions

ProjectPulse exposes reviewed project memory over MCP (`.mcp.json`). MCP does not call
tools automatically — follow this order for every coding task:

1. **Before implementing:** call `projectpulse_brief` with the ProjectPulse project UUID
   and the task. Follow every applied record unless the task explicitly changes one;
   if you must break one, do the task the compliant way and say so.
2. **Before finishing:** call `projectpulse_check` with your code, diff or plan and fix
   every violation it reports.
3. **When the session ends:** call `projectpulse_submit_session` with the transcript so
   the team can review proposed memory in the Inbox. Nothing is remembered unreviewed.
4. For "why" questions about past decisions, call `projectpulse_ask`.

If no project UUID is known, ask the developer to pick one in the dashboard
(Settings → Connect a coding agent) and provide its ID.

Never send secrets, API keys, passwords or personal data to any tool. Do not submit
transient status updates. The legacy `recall_project_memory` / `retain_project_memory`
tools still work but bypass the review gate — prefer the governed tools above.
