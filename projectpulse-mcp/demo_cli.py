"""Real MCP stdio tool-call demo; the sample coding result is labelled."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from sqlalchemy import select

from app.config import get_settings
from app.db.database import SessionLocal
from app.models.entities import AgentSession, Project
from app.services.audit_event_service import AuditEventService

TASK = "Implement login and refresh-token flow for this project."


async def main(project_id: str | None) -> None:
    with SessionLocal() as db:
        if project_id:
            project = db.get(Project, project_id)
        else:
            project = db.scalar(
                select(Project).where(Project.name == "E-commerce Platform")
            )
        if not project:
            raise SystemExit("Create or launch the E-commerce project first.")
        project_id = project.id

    settings = get_settings()
    forwarded_env = {"DATABASE_URL": settings.database_url}
    if settings.hindsight_api_key:
        forwarded_env["HINDSIGHT_API_KEY"] = settings.hindsight_api_key
        forwarded_env["HINDSIGHT_BASE_URL"] = settings.hindsight_base_url
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "projectpulse-mcp" / "server.py")],
        cwd=str(ROOT),
        env=forwarded_env,
    )
    async with Client(params) as client:
        print("Actual MCP tool call: projectpulse.recall_project_memory")
        result = await client.call_tool(
            "recall_project_memory",
            {"project_id": project_id, "task_description": TASK, "top_k": 5},
        )
        if result.is_error:
            raise SystemExit(str(result.content))
        payload = result.structured_content
        if not isinstance(payload, dict):
            try:
                payload = json.loads(result.content[0].text)
            except (IndexError, AttributeError, ValueError) as exc:
                raise SystemExit("MCP returned no structured result.") from exc

    memories = payload.get("memories", [])
    print(
        json.dumps(
            {
                "project_id": project_id,
                "mode": payload.get("mode_label"),
                "session_id": payload.get("session_id"),
                "recalled": memories,
            },
            indent=2,
            default=str,
        )
    )
    jwt_seen = any(
        "http-only" in memory.get("text", "").lower()
        or "httponly" in memory.get("text", "").lower()
        for memory in memories
    )
    if jwt_seen:
        sample = (
            "Local CLI sample result (not an external coding agent): "
            "Implement login with short-lived access tokens and refresh tokens in "
            "HttpOnly, Secure cookies; avoid LocalStorage. Read the refresh cookie "
            "server-side and rotate it on refresh."
        )
    else:
        sample = (
            "Local CLI sample result (not an external coding agent): "
            "No JWT rule was recalled. Ask for the project's auth convention "
            "before choosing refresh-token storage."
        )
    print(sample)
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        session = db.get(AgentSession, payload["session_id"])
        AuditEventService.activity(
            db,
            project,
            session,
            "agent_result",
            sample,
            payload["origin"],
            evidence=memories,
        )
        db.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", help="Defaults to E-commerce Platform")
    args = parser.parse_args()
    asyncio.run(main(args.project_id))
