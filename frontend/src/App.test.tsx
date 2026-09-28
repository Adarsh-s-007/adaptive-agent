import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";
import type { Activity, Event, Memory, Project } from "./api";

const project: Project = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "E-commerce Platform",
  description: "Storefront demo",
  hindsight_bank_id: "demo-projectpulse-e-commerce-platform-11111111",
  memory_mode: "demo",
  created_at: "2026-09-28T10:00:00Z",
};
const jwt: Memory = {
  id: "jwt-fact",
  text: "JWT refresh tokens must use HTTP-only, Secure cookies. LocalStorage is forbidden.",
  type: "security_rule",
  tags: ["project:" + project.id, "authentication", "security"],
  metadata: { memory_type: "security_rule", source_agent: "Agent A - previous session" },
  source_agent: "Agent A - previous session",
  session_id: "agent-a-session",
  timestamp: "2026-09-28T10:00:00Z",
  origin: "demo",
};

function response(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body } as Response;
}

describe("ProjectPulse MCP dashboard", () => {
  let projects: Project[];
  let events: Event[];
  let memories: Memory[];
  let activities: Activity[];
  let calls: Array<{ path: string; method: string; body: unknown }>;

  beforeEach(() => {
    projects = [];
    events = [];
    memories = [];
    activities = [];
    calls = [];

    vi.stubGlobal("fetch", vi.fn(async (input: string, options?: RequestInit) => {
      const path = new URL(input).pathname;
      const method = options?.method || "GET";
      const body = options?.body ? JSON.parse(String(options.body)) : null;
      calls.push({ path, method, body });

      if (path === "/health") return response({
        status: "ok", hindsight_configured: false, groq_configured: false,
      });
      if (path === "/projects" && method === "GET") return response(projects);
      if (path === "/projects" && method === "POST") {
        projects = [project];
        return response(project, 201);
      }
      if (path.endsWith("/seed-demo-data")) {
        memories = [jwt];
        events = [{
          id: "seed-event",
          event_type: "retained",
          source_text: "Memory type: security_rule\nSource agent: Agent A - previous session\nDecision / learning: " + jwt.text,
          created_at: "2026-09-28T10:00:00Z",
          session_id: "agent-a-session",
          agent_name: "Agent A - previous session",
        }];
        return response({ seeded: 8, mode_label: "Demo mode - local sample memory" });
      }
      if (path.endsWith("/timeline")) return response(events);
      if (path.endsWith("/stats")) return response({
        retained: memories.length, recalled: activities.some((item) => item.kind === "recall_evidence") ? 1 : 0,
        decisions: 0, bug_fixes: 0,
      });
      if (path.endsWith("/activity")) return response(activities);
      if (path.endsWith("/memories") && method === "GET") return response({
        memories, count: memories.length, origin: "demo",
        mode_label: "Demo mode - local sample memory", used_bank_id: project.hindsight_bank_id,
      });
      if (path.endsWith("/memories") && method === "POST") {
        memories = [{ ...jwt, id: "manual-memory", text: body.content }, ...memories];
        return response({ event: events[0], memory: memories[0], origin: "demo" }, 201);
      }
      if (path.endsWith("/run-mcp-demo")) {
        activities = [
          { id: "result", kind: "agent_result", tool_name: null,
            summary: "Local sample result: use HttpOnly, Secure cookies. Do not use LocalStorage.",
            evidence: [jwt], origin: "demo", session_id: "agent-b", agent_name: "Fresh Agent B",
            created_at: "2026-09-28T10:05:03Z" },
          { id: "recall", kind: "recall_evidence", tool_name: null,
            summary: "Recalled 1 relevant project memories", evidence: [jwt],
            origin: "demo", session_id: "agent-b", agent_name: "Fresh Agent B",
            created_at: "2026-09-28T10:05:02Z" },
          { id: "tool", kind: "tool_call", tool_name: "projectpulse.recall_project_memory",
            summary: "Implement login and refresh-token flow for this project.",
            evidence: [jwt], origin: "demo", session_id: "agent-b", agent_name: "Fresh Agent B",
            created_at: "2026-09-28T10:05:01Z" },
          { id: "session", kind: "session_started", tool_name: null,
            summary: "Fresh Agent B session started", evidence: [], origin: "demo",
            session_id: "agent-b", agent_name: "Fresh Agent B",
            created_at: "2026-09-28T10:05:00Z" },
        ];
        events = [{ id: "recall-event", event_type: "recalled",
          source_text: "Implement login and refresh-token flow for this project.",
          created_at: "2026-09-28T10:05:02Z", session_id: "agent-b",
          agent_name: "Fresh Agent B" }, ...events];
        return response({
          tool_call: "projectpulse.recall_project_memory",
          task: "Implement login and refresh-token flow for this project.",
          memories: [jwt],
          sample_result: activities[0].summary,
          session_id: "agent-b",
          origin: "demo",
          mode_label: "Demo mode - local sample memory",
        });
      }
      return response({ detail: "Not found" }, 404);
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("keeps the demo and retain flow, then shows evidence from an actual MCP action", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByText("Persistent project memory for coding agents.")).toBeTruthy();
    await user.click(screen.getAllByRole("button", { name: "Launch E-commerce MCP demo" })[0]);
    expect(await screen.findByText(/Agent A retained 8 sample engineering memories/)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Memory timeline" }));
    expect(await screen.findByText(jwt.text)).toBeTruthy();
    await user.click(screen.getAllByRole("button", { name: /Retain memory/ })[0]);
    await user.click(screen.getByRole("button", { name: "Use JWT demo decision" }));
    await user.click(screen.getByRole("button", { name: "Retain in Demo mode" }));
    expect(await screen.findByText(/Memory saved in Demo mode/)).toBeTruthy();
    expect(calls.some((call) => call.path.endsWith("/memories") &&
      call.method === "POST" && JSON.stringify(call.body).includes("HTTP-only"))).toBe(true);

    await user.click(screen.getByRole("button", { name: "Agent activity" }));
    await user.click(screen.getByRole("button", { name: "Run fresh Agent B MCP demo" }));
    expect(await screen.findByText(/official MCP client called recall_project_memory/)).toBeTruthy();
    expect(screen.getByText("WHY THIS ANSWER IS PROJECT-AWARE")).toBeTruthy();
    expect(screen.getByText("projectpulse.recall_project_memory")).toBeTruthy();
    expect(screen.getAllByText(/use HttpOnly, Secure cookies/)[0]).toBeTruthy();
    expect(calls.some((call) => call.path.endsWith("/run-mcp-demo") &&
      call.method === "POST")).toBe(true);
  });
});


