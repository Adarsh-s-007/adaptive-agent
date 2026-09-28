// Typed client for the ProjectPulse /api/v1 contract.

export const API_BASE: string = (import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

const TOKEN_KEY = "pp.access_token";
let accessToken: string | null = null;
try {
  accessToken = sessionStorage.getItem(TOKEN_KEY);
} catch {
  accessToken = null;
}

export function setAccessToken(token: string | null) {
  accessToken = token;
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
}

export class ApiError extends Error {
  status: number;
  code: string;
  requestId?: string;
  details?: Record<string, unknown>;
  constructor(status: number, code: string, message: string, requestId?: string, details?: Record<string, unknown>) {
    super(message);
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }
}

type Listener = (error: ApiError) => void;
const authListeners = new Set<Listener>();
export function onAuthError(listener: Listener) {
  authListeners.add(listener);
  return () => authListeners.delete(listener);
}

export async function request<T>(path: string, options: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...(options.headers as Record<string, string>) };
  let body = options.body;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, headers, body });
  } catch {
    throw new ApiError(0, "NETWORK", "Cannot reach the ProjectPulse API. Is the backend running?");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const err = payload?.error;
    const message = err?.message || (typeof payload?.detail === "string" ? payload.detail : `Request failed (HTTP ${response.status}).`);
    const error = new ApiError(response.status, err?.code || `HTTP_${response.status}`, message, err?.request_id || response.headers.get("X-Request-ID") || undefined, err?.details);
    if (response.status === 401) authListeners.forEach((l) => l(error));
    throw error;
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

// ------------------------------------------------------------------ types
export type MemoryType =
  | "decision" | "security_constraint" | "convention" | "api_contract"
  | "incident" | "failed_approach" | "deployment" | "preference";

export interface RecordRef {
  id: string;
  pill: string;
  type: MemoryType;
  title: string;
  statement: string;
  rationale?: string | null;
  area?: string | null;
  applies_to: string[];
  importance: number;
  status: "active" | "superseded" | "retracted";
  confidence_band: "high" | "medium" | "low";
  decided_at?: string | null;
  tentative: boolean;
  review_due: boolean;
  retain_state?: string | null;
}

export interface MemoryRecord extends RecordRef {
  project_id: string;
  type_label: string;
  confidence?: number | null;
  stated_by?: string | null;
  source?: string | null;
  tags: string[];
  hindsight_document_id: string;
  retry_count: number;
  last_error?: string | null;
  supersedes_id?: string | null;
  superseded_by_id?: string | null;
  source_session_id?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  review_due_at?: string | null;
  retired_at?: string | null;
  retract_reason?: string | null;
  check_patterns: string[];
  times_applied: number;
  times_violated: number;
  evidence_count: number;
  created_at: string;
  retained_content?: string | null;
  evidence?: { id: string; quote: string; speaker: string; turn_index?: number | null; source_session_id?: string | null; created_at: string }[];
  version_chain?: (RecordRef & { relation: "older" | "newer" | "this" })[];
  applied_in?: { run_id: string; task: string; created_at: string }[];
  violated_in?: { check_id: string; run_id?: string | null; excerpt: string; created_at: string }[];
  source_session?: Session;
  hindsight_document?: { id: string; tags: string[]; memory_unit_count: number; nodes_by_fact_type?: Record<string, number>; updated_at?: string } | null;
}

export interface ProjectStats {
  active_records: number;
  superseded_records: number;
  retracted_records: number;
  pending_candidates: number;
  last_activity_at?: string | null;
  active_by_type?: Record<string, number>;
  unsynced_records?: number;
  sessions?: number;
  comparisons?: number;
  isolation_violations_blocked?: number;
}

export interface Project {
  id: string;
  name: string;
  slug?: string | null;
  description: string;
  tech_stack: string;
  areas: string[];
  bank_id: string;
  bank_status: "provisioning" | "ready" | "error";
  bank_error?: string | null;
  memory_mode: "hindsight" | "demo";
  created_at: string;
  stats: ProjectStats;
}

export interface Turn {
  id: string;
  seq: number;
  role: "human" | "agent" | "tool";
  speaker?: string | null;
  content: string;
  run_id?: string | null;
  meta: Record<string, unknown>;
  created_at: string;
  run?: {
    id: string;
    mode: string;
    brief: Brief | null;
    recall_ms: number;
    filter_ms: number;
    llm_ms: number;
    injected_tokens: number;
    files: GeneratedFile[];
    notes: string[];
    followed_record_ids: string[];
    model?: string | null;
  };
}

export interface Session {
  id: string;
  project_id: string;
  title: string;
  developer?: string | null;
  agent_label?: string | null;
  source: string;
  status: "open" | "closed" | "extracted";
  occurred_at?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  extraction_error?: string | null;
  extraction_stats: Record<string, unknown>;
  turn_count: number;
  pending_candidates?: number;
  turns?: Turn[];
  candidates?: Candidate[];
}

export interface Candidate {
  id: string;
  session_id: string;
  type: MemoryType;
  title: string;
  statement: string;
  rationale?: string | null;
  area?: string | null;
  applies_to: string[];
  importance: number;
  stated_by: string;
  evidence_quote: string;
  evidence_turn_ids: number[];
  status: "pending" | "approved" | "rejected" | "auto_rejected";
  filter_reason?: string | null;
  relation: "new" | "duplicate" | "refines" | "conflicts" | "supersedes";
  related_record_id?: string | null;
  related_record?: RecordRef | null;
  relation_reason?: string | null;
  confidence: number;
  confidence_band: "high" | "medium" | "low";
  flagged: boolean;
  flags: string[];
  extractor_model?: string | null;
  record_id?: string | null;
  created_at: string;
}

export interface InboxGroup {
  session: Session;
  pending: Candidate[];
  filtered: Candidate[];
  reviewed: Candidate[];
}

export interface Brief {
  status: "ok" | "empty" | "memory_unavailable" | "unfiltered" | "none_apply";
  message?: string | null;
  query: string;
  recalled: RecordRef[];
  applied: { record: RecordRef; rank: number; recall_rank?: number | null; score?: number | null; reason: string }[];
  filtered: { record: RecordRef; recall_rank?: number | null; reason: string }[];
  observations: { text: string; record_ids: string[] }[];
  filter_mode: "llm" | "heuristic" | "unfiltered" | "none";
  recall_ms: number;
  filter_ms: number;
  recall_attempts: number;
  injected_tokens: number;
  all_records_tokens: number;
  active_records: number;
  memory_block: string;
}

export interface GeneratedFile { path: string; language: string; content: string }

export interface TaskRun {
  id: string;
  mode: "baseline" | "memory";
  task: string;
  status: "ok" | "error" | "blocked";
  error?: { code: string; message: string; details?: Record<string, unknown> } | null;
  model?: string | null;
  output: { summary: string; files: GeneratedFile[]; notes: string[]; followed_record_ids: string[] };
  brief?: Brief | null;
  usage: { prompt_tokens?: number; completion_tokens?: number };
  injected_tokens: number;
  recall_ms: number;
  filter_ms: number;
  llm_ms: number;
  latency_ms: number;
  created_at: string;
}

export interface Finding {
  record_id: string;
  record_pill: string;
  record_title: string;
  severity: "high" | "medium" | "low";
  rule_statement: string;
  excerpt: string;
  explanation: string;
  suggested_fix: string;
  pattern_evidence: string[];
  tentative: boolean;
}

export interface CheckResult {
  id?: string | null;
  verdict: "compliant" | "violations" | "unavailable";
  message?: string | null;
  summary: string;
  judge_mode: "llm" | "heuristic" | "none";
  judge_model?: string | null;
  violations: Finding[];
  warnings: Finding[];
  conflicts: { record_ids: string[]; record_pills: string[]; explanation: string }[];
  recalled_records: RecordRef[];
  dropped_findings: number;
  checked_tokens: number;
  latency_ms: number;
}

export interface CompareResult {
  id: string;
  status: "running" | "completed" | "failed";
  stage: string;
  task: string;
  repeats: number;
  baseline_run?: TaskRun | null;
  memory_run?: TaskRun | null;
  baseline_check?: CheckResult | null;
  memory_check?: CheckResult | null;
  baseline_runs: TaskRun[];
  memory_runs: TaskRun[];
  baseline_checks: CheckResult[];
  memory_checks: CheckResult[];
  violations_baseline: number;
  violations_memory: number;
  violation_delta: number;
  applied_count: number;
  injected_tokens: number;
  summary: Record<string, unknown> & {
    violations_baseline_per_run?: number[];
    violations_memory_per_run?: number[];
    all_records_tokens?: number;
    records_recalled?: number;
    records_filtered?: number;
    records_followed?: number;
    prompt_token_difference?: number | null;
    memory_utilisation?: number | null;
  };
  fairness: { line?: string; model?: string };
  error?: { code: string; message: string } | null;
  created_at: string;
}

export interface ComparisonRow {
  id: string;
  task: string;
  status: string;
  stage: string;
  repeats: number;
  violations_baseline: number;
  violations_memory: number;
  violation_delta: number;
  summary: Record<string, unknown>;
  created_at: string;
}

export interface Rulebook {
  content: string;
  last_refreshed_at?: string | null;
  is_stale: boolean;
  status: "ready" | "generating" | "offline" | "error";
  source: string;
  message?: string;
}

export interface TimelineItem {
  id: string;
  kind: "approved" | "seeded" | "superseded" | "retracted" | "session" | "rulebook_refreshed" | "comparison";
  at?: string | null;
  title: string;
  summary: string;
  record?: RecordRef;
  previous?: RecordRef;
  actor?: string | null;
  session_id?: string;
  comparison_id?: string;
}

export interface AskAnswer {
  question: string;
  answer: string;
  based_on: RecordRef[];
  facts: { id: string; text: string; type: string; record_ids: string[] }[];
  guardrails: { name: string; content: string }[];
  latency_ms: number;
}

export interface Metrics {
  records: { total: number; active: number; superseded: number; retracted: number; by_type: Record<string, number>; unsynced: number; review_due: number; tentative: number };
  violation_delta: { last_10: { comparison_id: string; task: string; baseline: number; memory: number; delta: number; created_at: string }[]; median: number | null };
  latency: { recall_p50_ms: number | null; recall_p95_ms: number | null; brief_p50_ms: number | null; brief_p95_ms: number | null; samples: number };
  tokens: { injected_avg: number | null; memory_runs: number };
  memory_utilisation: number | null;
  extraction_yield: Record<string, number>;
  checks: { total: number; with_violations: number; violations_found: number };
  application: (RecordRef & { times_applied: number; times_violated: number })[];
  isolation_violations_blocked: number;
  eval: { id: string; precision: number | null; recall: number | null; forbidden_rate: number | null; created_at: string; models: Record<string, string> } | null;
}

export interface EvalRun {
  id: string;
  set: string;
  precision: number | null;
  recall: number | null;
  forbidden_rate: number | null;
  models: Record<string, string>;
  results: { id: string; task: string; applied: string[]; expected: string[]; missing_labels: string[]; forbidden_applied: string[]; precision: number; recall: number; brief_status: string; filter_mode: string; recall_ms: number }[];
  created_at: string;
}

export interface Status {
  hindsight: { status: string; latency_ms?: number; message?: string };
  llm: { status: string; latency_ms?: number; message?: string; large?: string; small?: string };
  demo_mode: boolean;
  force_offline: boolean;
  auth_required: boolean;
  models: { large: string; small: string };
}

export interface BankSummary {
  bank_id: string;
  bank_status: string;
  bank_error?: string | null;
  available: boolean;
  config: Record<string, unknown> | null;
  directives: { name: string; content: string; is_active: boolean }[];
  stats: Record<string, unknown> | null;
  error?: string;
}

export interface AuditEvent {
  id: string;
  event_type: string;
  status: string;
  latency_ms?: number | null;
  record_id?: string | null;
  actor?: string | null;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface DemoTask { id: string; label: string; task: string; expect: string }

// ------------------------------------------------------------------ endpoints
const p = (pid: string) => `/api/v1/projects/${pid}`;

export const api = {
  status: () => request<Status>("/api/v1/status"),
  demoTasks: () => request<DemoTask[]>("/api/v1/demo-tasks"),
  projects: () => request<Project[]>("/api/v1/projects"),
  project: (pid: string) => request<Project>(p(pid)),
  createProject: (body: { name: string; description: string; tech_stack: string; areas: string[] }) =>
    request<Project>("/api/v1/projects", { method: "POST", json: body }),
  provision: (pid: string) => request<{ bank_status: string }>(`${p(pid)}/provision?force=true`, { method: "POST" }),
  bank: (pid: string) => request<BankSummary>(`${p(pid)}/bank`),
  seed: (project: "apexcart" | "ledgerlite", reset = false) =>
    request<{ project_id: string; records_created: number; transcripts_imported: number }>("/api/v1/admin/seed", { method: "POST", json: { project, reset } }),
  resetProject: (pid: string) => request(`${p(pid)}/reset`, { method: "POST" }),
  setOffline: (force_offline: boolean) => request<{ force_offline: boolean }>("/api/v1/admin/hindsight/offline", { method: "POST", json: { force_offline } }),

  sessions: (pid: string) => request<Session[]>(`${p(pid)}/sessions`),
  session: (pid: string, sid: string) => request<Session>(`${p(pid)}/sessions/${sid}`),
  createSession: (pid: string, body: { title: string; developer: string; agent_label: string }) =>
    request<Session>(`${p(pid)}/sessions`, { method: "POST", json: body }),
  importSession: (pid: string, body: { title: string; developer: string; agent_label: string; text: string; format: string }) =>
    request<{ session_id: string }>(`${p(pid)}/sessions/import`, { method: "POST", json: body }),
  sendMessage: (pid: string, sid: string, body: { content: string; use_memory: boolean }) =>
    request<{ human_turn: Turn; assistant_turn: Turn | null; run: TaskRun; brief: Brief | null; error?: { code: string; message: string } }>(
      `${p(pid)}/sessions/${sid}/messages`, { method: "POST", json: body }),
  closeSession: (pid: string, sid: string) =>
    request<{ session: Session; candidates: Candidate[]; filtered: Candidate[]; stats: Record<string, unknown> }>(
      `${p(pid)}/sessions/${sid}/close`, { method: "POST", json: { extract: true } }),
  extractSession: (pid: string, sid: string) =>
    request<{ candidates: Candidate[]; filtered: Candidate[]; stats: Record<string, unknown> }>(`${p(pid)}/sessions/${sid}/extract`, { method: "POST" }),
  remember: (pid: string, sid: string, tid: string, body: { title: string; statement: string; type: string; area?: string; quote?: string; reviewer: string }) =>
    request<MemoryRecord>(`${p(pid)}/sessions/${sid}/turns/${tid}/remember`, { method: "POST", json: body }),

  inbox: (pid: string) => request<{ groups: InboxGroup[]; counts: { pending: number; filtered: number; reviewed: number } }>(`${p(pid)}/inbox`),
  approve: (pid: string, cid: string, body: { reviewer: string; resolution?: string; target_record_id?: string | null; edits?: Record<string, unknown> }) =>
    request<{ record?: MemoryRecord; superseded_record?: MemoryRecord; resolution: string }>(`${p(pid)}/candidates/${cid}/approve`, { method: "POST", json: body }),
  reject: (pid: string, cid: string, body: { reviewer: string; reason: string }) =>
    request<Candidate>(`${p(pid)}/candidates/${cid}/reject`, { method: "POST", json: body }),
  approveHighConfidence: (pid: string, reviewer: string) =>
    request<{ approved: number }>(`${p(pid)}/candidates/approve-high-confidence`, { method: "POST", json: { reviewer } }),

  memories: (pid: string, params: { status?: string; type?: string; area?: string; q?: string } = {}) => {
    const qs = new URLSearchParams(Object.entries({ status: "all", ...params }).filter(([, v]) => v) as [string, string][]);
    return request<MemoryRecord[]>(`${p(pid)}/memories?${qs}`);
  },
  memory: (pid: string, rid: string) => request<MemoryRecord>(`${p(pid)}/memories/${rid}`),
  createMemory: (pid: string, body: Record<string, unknown>) => request<MemoryRecord>(`${p(pid)}/memories`, { method: "POST", json: body }),
  supersede: (pid: string, rid: string, body: Record<string, unknown>) =>
    request<{ record: MemoryRecord; superseded_record: MemoryRecord }>(`${p(pid)}/memories/${rid}/supersede`, { method: "POST", json: body }),
  retract: (pid: string, rid: string, body: { reason: string; reviewer: string }) =>
    request<MemoryRecord>(`${p(pid)}/memories/${rid}/retract`, { method: "POST", json: body }),
  retry: (pid: string, rid: string) => request<MemoryRecord>(`${p(pid)}/memories/${rid}/retry`, { method: "POST" }),
  flushOutbox: (pid: string) => request<{ synced: number; failed: number }>(`${p(pid)}/outbox/flush`, { method: "POST" }),

  brief: (pid: string, task: string) => request<Brief>(`${p(pid)}/brief`, { method: "POST", json: { task } }),
  run: (pid: string, body: { task: string; mode: "baseline" | "memory" }) => request<TaskRun>(`${p(pid)}/runs`, { method: "POST", json: body }),
  startCompare: (pid: string, body: { task: string; repeats: number }) =>
    request<{ comparison_id: string }>(`${p(pid)}/compare`, { method: "POST", json: body }),
  comparison: (pid: string, cid: string) => request<CompareResult>(`${p(pid)}/compare/${cid}`),
  comparisons: (pid: string) => request<ComparisonRow[]>(`${p(pid)}/compare`),
  check: (pid: string, content: string, run_id?: string) =>
    request<CheckResult>(`${p(pid)}/check`, { method: "POST", json: { content, run_id } }),
  ask: (pid: string, question: string) => request<AskAnswer>(`${p(pid)}/ask`, { method: "POST", json: { question } }),
  rulebook: (pid: string) => request<Rulebook>(`${p(pid)}/rulebook`),
  refreshRulebook: (pid: string) => request<{ operation_id: string }>(`${p(pid)}/rulebook/refresh`, { method: "POST" }),
  rulebookHistory: (pid: string) => request<{ changed_at: string; content: string; source: string; active_record_count?: number | null }[]>(`${p(pid)}/rulebook/history`),
  exportRulebook: (pid: string, format: "claude_md" | "cursorrules") =>
    request<{ filename: string; content: string; records: number }>(`${p(pid)}/rulebook/export?format=${format}`),
  timeline: (pid: string) => request<TimelineItem[]>(`${p(pid)}/timeline`),
  metrics: (pid: string) => request<Metrics>(`${p(pid)}/metrics`),
  audit: (pid: string) => request<AuditEvent[]>(`${p(pid)}/audit?limit=60`),
  runEval: (pid: string) => request<EvalRun>(`${p(pid)}/eval`, { method: "POST", json: { set: "default" } }),
  evals: (pid: string) => request<EvalRun[]>(`${p(pid)}/eval`),
};

/** Stream Compare stages over SSE, falling back to 1 s polling. Returns an unsubscribe. */
export function streamComparison(
  pid: string,
  cid: string,
  onStage: (stage: string, result?: CompareResult) => void,
  onError: (error: Error) => void,
): () => void {
  let closed = false;
  const controller = new AbortController();
  const poll = async () => {
    while (!closed) {
      try {
        const result = await api.comparison(pid, cid);
        onStage(result.stage, result.status === "running" ? undefined : result);
        if (result.status !== "running") return;
      } catch (e) {
        onError(e as Error);
        return;
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
  };
  (async () => {
    try {
      const headers: Record<string, string> = { Accept: "text/event-stream" };
      if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
      const response = await fetch(`${API_BASE}${p(pid)}/compare/${cid}`, { headers, signal: controller.signal });
      if (!response.ok || !response.body) throw new Error("SSE unavailable");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!closed) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";
        for (const chunk of events) {
          const data = chunk.split("\n").find((l) => l.startsWith("data: "));
          if (!data) continue;
          const payload = JSON.parse(data.slice(6));
          onStage(payload.stage, payload.result);
          if (payload.status && payload.status !== "running") return;
        }
      }
    } catch {
      if (!closed) void poll();
    }
  })();
  return () => {
    closed = true;
    controller.abort();
  };
}
