# ProjectPulse agent instructions

Before implementing any coding task, call `recall_project_memory` with the current
ProjectPulse project UUID and the task description. Follow relevant returned
decisions. If no project UUID is known, ask the developer to select/create one
in the dashboard and provide its ID.

After resolving a durable engineering decision, incident, convention, or API
contract, call `retain_project_memory`. Never retain secrets, API keys,
passwords, or personal data. Do not retain transient status updates.

The MCP server is configured in `.mcp.json`. Its tools are not called
automatically by MCP itself; these instructions direct when to call them.
