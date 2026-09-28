import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";
import type { Event, Project } from "./api";

const project: Project = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "E-commerce Platform",
  description: "Storefront demo",
  hindsight_bank_id: "projectpulse-e-commerce-platform-11111111",
  created_at: "2026-09-28T10:00:00Z",
};

function response(body: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    json: async () => body,
  } as Response;
}

describe("ProjectPulse dashboard demo", () => {
  let projects: Project[];
  let events: Event[];
  let retained: number;
  let recalled: number;
  let calls: Array<{ path: string; method: string; body: unknown }>;

  beforeEach(() => {
    projects = [];
    events = [];
    retained = 0;
    recalled = 0;
    calls = [];

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, options?: RequestInit) => {
        const path = new URL(input).pathname;
        const method = options?.method || "GET";
        const body = options?.body ? JSON.parse(String(options.body)) : null;
        calls.push({ path, method, body });

        if (path === "/health") {
          return response({ status: "ok", hindsight_configured: true, groq_configured: true });
        }
        if (path === "/projects" && method === "GET") return response(projects);
        if (path === "/projects" && method === "POST") {
          projects = [{ ...project, description: body.description }];
          return response(projects[0], 201);
        }
        if (path.endsWith("/seed-demo-data")) {
          retained = 8;
          events = [{
            id: "seed-event",
            event_type: "retained",
            source_text:
              "Memory type: architecture decision\nSource agent: Agent A - previous session\nProject: E-commerce Platform\nDecision / learning: JWT refresh tokens use HTTP-only cookies.",
            created_at: "2026-09-28T10:00:00Z",
            session_id: "agent-a-session",
            agent_name: "Agent A - previous session",
          }];
          return response({ seeded: 8 });
        }
        if (path.endsWith("/timeline")) return response(events);
        if (path.endsWith("/stats")) {
          return response({ retained, recalled, decisions: retained ? 1 : 0, bug_fixes: 0 });
        }
        if (path.endsWith("/memories")) {
          retained += 1;
          const event: Event = {
            id: "manual-event",
            event_type: "retained",
            source_text:
              "Memory type: " + body.memory_type +
              "\nSource agent: " + body.source_agent +
              "\nProject: E-commerce Platform\nDecision / learning: " + body.content,
            created_at: "2026-09-28T10:04:00Z",
            session_id: "agent-a-session",
            agent_name: body.source_agent,
          };
          events = [event, ...events];
          return response({ event }, 201);
        }
        if (path.endsWith("/agent-answer")) {
          recalled += 1;
          events = [{
            id: "recall-event",
            event_type: "recalled",
            source_text: body.task,
            created_at: "2026-09-28T10:05:00Z",
            session_id: "agent-b-session",
            agent_name: body.agent_name,
          }, ...events];
          return response({
            generic_answer: "Build a login form and handle errors.",
            memory_aware_answer:
              "Use HTTP-only cookies for JWT refresh tokens and avoid localStorage.",
            memories: [{
              id: "jwt-fact",
              text: "JWT refresh tokens must use HTTP-only cookies; avoid localStorage.",
              type: "world",
              metadata: {
                memory_type: "architecture decision",
                source_agent: "Agent A - previous session",
              },
              timestamp: "2026-09-28T10:00:00Z",
              source_text: "Agent A retained the JWT cookie rule.",
              why_relevant: "Authentication uses the project's refresh-token rule.",
            }],
            used_bank_id: project.hindsight_bank_id,
            session: { id: "agent-b-session", agent_name: body.agent_name },
            event: events[0],
          });
        }
        return response({ detail: "Not found" }, 404);
      })
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("seeds, retains through the form, and shows Agent B's memory evidence", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText("A memory layer for every engineering agent.")).toBeTruthy();
    await user.click(screen.getAllByRole("button", { name: "Launch E-commerce demo" })[0]);
    expect(await screen.findByText(/Agent A retained 8 demo memories/)).toBeTruthy();
    expect(screen.getByText(project.hindsight_bank_id)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /Retain learning/ }));
    await user.click(screen.getByRole("button", { name: "Use JWT demo decision" }));
    await user.click(screen.getByRole("button", { name: "Retain in Hindsight" }));
    expect(await screen.findByText(/retained a project memory in Hindsight/)).toBeTruthy();
    expect(calls.some((call) =>
      call.path.endsWith("/memories") &&
      call.method === "POST" &&
      JSON.stringify(call.body).includes("HTTP-only cookies")
    )).toBe(true);

    await user.click(screen.getByRole("button", { name: /Ask ProjectPulse/ }));
    expect(await screen.findByText(/This answer used 1 relevant project memory/)).toBeTruthy();
    expect(screen.getByText("Build a login form and handle errors.")).toBeTruthy();
    expect(screen.getByText(/Use HTTP-only cookies for JWT refresh tokens and avoid localStorage/)).toBeTruthy();
    expect(screen.getByText(/Authentication uses the project's refresh-token rule/)).toBeTruthy();
    expect(calls.some((call) =>
      call.path.endsWith("/agent-answer") &&
      JSON.stringify(call.body).includes("Agent B - fresh session")
    )).toBe(true);
  });
});
