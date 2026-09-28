export const API = import.meta.env.VITE_API_URL || "http://localhost:8000";
const AUTH_HEADER = { Authorization: "Bearer dev-token-projectpulse" };

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
  bank_status?: string;
  memory_mode: "demo" | "hindsight";
  created_at: string;
};

export type Health = {
  status: string;
  hindsight_configured: boolean;
  groq_configured: boolean;
};

export type HindsightProbe = {
  configured: boolean;
  status: string;
  message: string;
  latency_ms?: number;
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

export type GovernedRecord = {
  id: string;
  pill: string;
  project_id: string;
  type: string;
  title: string;
  statement: string;
  rationale?: string;
  area?: string;
  importance: number;
  status: "active" | "superseded" | "retracted";
  confidence_band: string;
  supersedes_id?: string;
  superseded_by_id?: string;
  hindsight_document_id: string;
  retain_state: string;
  created_at: string;
};

export type TimelineItem = {
  id: string;
  event_type: string;
  timestamp: string;
  title: string;
  summary: string;
  pill?: string;
  record_id?: string;
  session_id?: string;
  actor: string;
  metadata: Record<string, any>;
};

export type ProjectMetrics = {
  project_id: string;
  bank_id: string;
  provider: string;
  provider_status: string;
  hindsight_latency_ms: number;
  isolation_score: number;
  isolation_violations_blocked: number;
  summary: {
    active_records: number;
    superseded_records: number;
    retracted_records: number;
    total_retained: number;
    pending_inbox_candidates: number;
    retention_health_pct: number;
  };
  by_type: Record<string, number>;
  by_area: Record<string, number>;
  guardrails: {
    total_checks: number;
    checks_passed: number;
    violations_prevented: number;
  };
};

export type RulebookData = {
  project_id: string;
  bank_id: string;
  rulebook: string;
  directives: Array<{ name: string; content: string }>;
};

export const api = {
  health: () => request<Health>("/health"),
  hindsightProbe: () => request<HindsightProbe>("/health/hindsight"),
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
  runMcpDemo: (id: string) =>
    request<McpDemo>(`/projects/${id}/run-mcp-demo`, { method: "POST" }),

  // V1 Governed Endpoints
  provisionBank: (id: string) =>
    request<{ project_id: string; bank_id: string; bank_status: string }>(
      `/api/v1/projects/${id}/provision`,
      { method: "POST", headers: AUTH_HEADER }
    ),
  getRulebook: (id: string) =>
    request<RulebookData>(`/api/v1/projects/${id}/rulebook`, { headers: AUTH_HEADER }),
  refreshRulebook: (id: string) =>
    request<RulebookData>(`/api/v1/projects/${id}/rulebook/refresh`, {
      method: "POST",
      headers: AUTH_HEADER,
    }),
  getMetrics: (id: string) =>
    request<ProjectMetrics>(`/api/v1/projects/${id}/metrics`, { headers: AUTH_HEADER }),
  getV1Timeline: (id: string) =>
    request<TimelineItem[]>(`/api/v1/projects/${id}/timeline`, { headers: AUTH_HEADER }),
  getGovernedRecords: (id: string, status?: string) =>
    request<GovernedRecord[]>(
      `/api/v1/projects/${id}/records${status ? `?status=${status}` : ""}`,
      { headers: AUTH_HEADER }
    ),
  seedEnterprise: (id: string, dataset: "apexcart" | "ledgerlite" = "apexcart") =>
    request<{ project_id: string; dataset: string; records_seeded: number; total_active: number }>(
      `/api/v1/projects/${id}/seed`,
      {
        method: "POST",
        headers: AUTH_HEADER,
        body: JSON.stringify({ dataset }),
      }
    ),
  createGovernedRecord: (
    id: string,
    body: {
      title: string;
      statement: string;
      memory_type: string;
      rationale?: string;
      area?: string;
      importance?: number;
      tags?: string[];
      check_patterns?: string[];
      evidence_quote?: string;
    }
  ) =>
    request<{ id: string; pill: string; status: string; retain_state: string; title: string }>(
      `/api/v1/projects/${id}/records`,
      { method: "POST", headers: AUTH_HEADER, body: JSON.stringify(body) }
    ),
  supersedeRecord: (
    id: string,
    recordId: string,
    body: {
      title: string;
      statement: string;
      rationale?: string;
      area?: string;
      importance?: number;
      evidence_quote?: string;
    }
  ) =>
    request<{ status: string; old_record_id: string; new_record_id: string; new_pill: string }>(
      `/api/v1/projects/${id}/records/${recordId}/supersede`,
      { method: "POST", headers: AUTH_HEADER, body: JSON.stringify(body) }
    ),
  retractRecord: (id: string, recordId: string, reason: string) =>
    request<{ status: string; record_id: string; pill: string }>(
      `/api/v1/projects/${id}/records/${recordId}/retract`,
      { method: "POST", headers: AUTH_HEADER, body: JSON.stringify({ reason }) }
    ),
  flushOutbox: (id: string) =>
    request<{ project_id: string; flushed: number; remaining: number }>(
      `/api/v1/projects/${id}/outbox/flush`,
      { method: "POST", headers: AUTH_HEADER }
    ),
  askProject: (id: string, question: string) =>
    request<{ answer: string; based_on: string[]; guardrails_applied: string[] }>(
      `/api/v1/projects/${id}/ask`,
      {
        method: "POST",
        headers: AUTH_HEADER,
        body: JSON.stringify({ question }),
      }
    ),
};
