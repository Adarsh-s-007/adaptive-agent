# ProjectPulse coding-agent instructions

Before implementing a coding task, call the ProjectPulse
`recall_project_memory` MCP tool with the current project UUID and task
description. Follow relevant returned memories. Ask for the project UUID if
it is not yet known.

After discovering a durable engineering decision, incident fix, API contract,
or convention, call `retain_project_memory`. Never retain secrets, API keys,
passwords, or personal data. Do not retain ephemeral status updates.

MCP availability does not automatically invoke these tools; use them explicitly
in this order for each task.
