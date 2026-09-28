export const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
  } catch {
    throw new Error("Cannot reach ProjectPulse API. Start the backend and retry.");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item: { msg?: string }) => item.msg || "Invalid field").join("; ")
          : `Request failed (HTTP ${response.status}).`;
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export type Project = {
  id: string;
  name: string;
  description: string;
  hindsight_bank_id: string;
  memory_mode: "demo" | "hindsight";
  created_at: string;
};

export type Health = {
  status: string;
  hindsight_configured: boolean;
  groq_configured: boolean;
};

export type Stats = {
  retained: number;
  recalled: number;
  decisions: number;
  bug_fixes: number;
};

export type Event = {
  id: string;
  event_type: "retained" | "recalled";
  source_text: string;
  created_at: string;
  session_id: string | null;
  agent_name: string | null;
};

export type Memory = {
  id: string;
  text: string;
  type: string;
  memory_type?: string;
  tags: string[];
  metadata: Record<string, string>;
  source_agent?: string | null;
  session_id?: string | null;
  document_id?: string | null;
  timestamp?: string | null;
  source_text?: string | null;
  origin: "demo" | "hindsight";
  why_relevant?: string | null;
};

export type MemoryList = {
  memories: Memory[];
  count: number;
  origin: "demo" | "hindsight";
  mode_label: string;
  used_bank_id: string;
};

export type Activity = {
  id: string;
  kind: string;
  tool_name: string | null;
  summary: string;
  evidence: Memory[];
  origin: "demo" | "hindsight";
  session_id: string | null;
  agent_name: string | null;
  created_at: string;
};

export type MemoryForm = {
  memory_type:
    | "architecture_decision"
    | "security_rule"
    | "api_contract"
    | "incident_fix"
    | "coding_convention";
  source_agent: string;
  content: string;
  tags: string[];
};

export type McpDemo = {
  tool_call: string;
  task: string;
  memories: Memory[];
  sample_result: string;
  session_id: string;
  origin: "demo" | "hindsight";
  mode_label: string;
};

export type RecallResult = {
  memories: Memory[];
  event: Event;
  used_bank_id: string;
  origin: "demo" | "hindsight";
};

export const api = {
  health: () => request<Health>("/health"),
  projects: () => request<Project[]>("/projects"),
  createProject: (body: { name: string; description: string }) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(body) }),
  timeline: (id: string) => request<Event[]>(`/projects/${id}/timeline`),
  stats: (id: string) => request<Stats>(`/projects/${id}/stats`),
  activity: (id: string) => request<Activity[]>(`/projects/${id}/activity`),
  memories: (id: string) => request<MemoryList>(`/projects/${id}/memories`),
  seed: (id: string) =>
    request<{ seeded: number; mode_label: string }>(`/projects/${id}/seed-demo-data`, {
      method: "POST",
    }),
  retain: (id: string, body: MemoryForm) =>
    request<{ event: Event; memory: Memory; origin: string }>(`/projects/${id}/memories`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  recall: (id: string, body: { task: string; limit?: number; agentName?: string }) =>
    request<RecallResult>(`/projects/${id}/recall`, {
      method: "POST",
      body: JSON.stringify({
        task: body.task,
        limit: body.limit || 5,
        agent_name: body.agentName || "Workspace agent",
      }),
    }),
  runMcpDemo: (id: string) =>
    request<McpDemo>(`/projects/${id}/run-mcp-demo`, { method: "POST" }),
};
