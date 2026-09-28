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
  metadata: Record<string, string>;
  document_id?: string | null;
  timestamp?: string | null;
  source_text?: string | null;
  relevance?: number | null;
  why_relevant?: string | null;
};

export type Answer = {
  generic_answer: string;
  memory_aware_answer: string;
  memories: Memory[];
  used_bank_id: string;
  session: { id: string; agent_name: string; created_at: string };
  event: Event;
};

export type MemoryForm = {
  memory_type:
    | "architecture decision"
    | "coding convention"
    | "bug fix"
    | "failed approach"
    | "feature progress";
  source_agent: string;
  content: string;
};

export const api = {
  health: () => request<Health>("/health"),
  projects: () => request<Project[]>("/projects"),
  createProject: (body: { name: string; description: string }) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(body) }),
  timeline: (id: string) => request<Event[]>(`/projects/${id}/timeline`),
  stats: (id: string) => request<Stats>(`/projects/${id}/stats`),
  seed: (id: string) =>
    request<{ seeded: number }>(`/projects/${id}/seed-demo-data`, { method: "POST" }),
  retain: (id: string, body: MemoryForm) =>
    request<{ event: Event }>(`/projects/${id}/memories`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  ask: (id: string, body: { agent_name: string; task: string }) =>
    request<Answer>(`/projects/${id}/agent-answer`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
