import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Activity,
  api,
  Event,
  Health,
  McpDemo,
  Memory,
  MemoryForm,
  Project,
  Stats,
} from "./api";

type Tab = "overview" | "timeline" | "activity" | "setup";
type Target = "Claude Code" | "GitHub Copilot";

const EMPTY_STATS: Stats = { retained: 0, recalled: 0, decisions: 0, bug_fixes: 0 };
const JWT_EXAMPLE =
  "JWT refresh tokens must use HTTP-only, Secure cookies. LocalStorage is forbidden.";
const ROOT_PLACEHOLDER = "/absolute/path/to/ProjectPulse";

function timeLabel(value?: string | null): string {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unavailable"
    : new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(date);
}

function kindLabel(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter: string) => letter.toUpperCase());
}

function eventText(event: Event): string {
  return event.source_text.split("Decision / learning: ")[1] || event.source_text;
}

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [stats, setStats] = useState<Stats>(EMPTY_STATS);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [activities, setActivities] = useState<Activity[]>([]);
  const [tab, setTab] = useState<Tab>("overview");
  const [target, setTarget] = useState<Target>("Claude Code");
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [selectedMemory, setSelectedMemory] = useState<Memory | null>(null);
  const [modal, setModal] = useState<"project" | "memory" | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [retry, setRetry] = useState<(() => void) | null>(null);
  const [demoResult, setDemoResult] = useState<McpDemo | null>(null);

  async function loadProject(next: Project) {
    const [nextEvents, nextStats, nextMemories, nextActivities] = await Promise.all([
      api.timeline(next.id),
      api.stats(next.id),
      api.memories(next.id),
      api.activity(next.id),
    ]);
    setProject(next);
    setEvents(nextEvents);
    setStats(nextStats);
    setMemories(nextMemories.memories);
    setActivities(nextActivities);
  }

  async function perform(label: string, action: () => Promise<void>) {
    setBusy(label);
    setError("");
    setNotice("");
    setRetry(null);
    try {
      await action();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Something went wrong.");
      setRetry(() => () => void perform(label, action));
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    void api.health().then(setHealth).catch(() => setHealth(null));
    void api.projects()
      .then(async (list) => {
        setProjects(list);
        if (list[0]) await loadProject(list[0]);
      })
      .catch((cause) => {
        setError(cause instanceof Error ? cause.message : "Could not load projects.");
        setRetry(() => () => window.location.reload());
      });
  }, []);

  function openProject(next: Project) {
    setDemoResult(null);
    setTab("overview");
    void perform("refresh", () => loadProject(next));
  }

  function launchDemo() {
    void perform("demo", async () => {
      const latest = await api.projects();
      let demo = latest.find((item) => item.name === "E-commerce Platform");
      if (!demo) {
        demo = await api.createProject({
          name: "E-commerce Platform",
          description: "Shared engineering memory for storefront, payments, and authentication.",
        });
      }
      const result = await api.seed(demo.id);
      setProjects(await api.projects());
      setDemoResult(null);
      setTab("overview");
      await loadProject(demo);
      setNotice(
        result.seeded
          ? "Agent A retained " + result.seeded + " sample engineering memories. " + result.mode_label
          : "The E-commerce memory bank is ready. " + result.mode_label
      );
    });
  }

  function createProject(data: { name: string; description: string }) {
    void perform("project", async () => {
      const created = await api.createProject(data);
      setProjects(await api.projects());
      await loadProject(created);
      setTab("overview");
      setModal(null);
      setNotice(
        created.memory_mode === "demo"
          ? "Project created in Demo mode - local sample memory."
          : "Project created with an isolated Hindsight bank."
      );
    });
  }

  function retainMemory(data: MemoryForm) {
    if (!project) return;
    void perform("retain", async () => {
      await api.retain(project.id, data);
      await loadProject(project);
      setModal(null);
      setTab("timeline");
      setNotice(
        project.memory_mode === "demo"
          ? "Memory saved in Demo mode - local sample memory."
          : "Memory retained through Hindsight."
      );
    });
  }

  function runMcpDemo() {
    if (!project) return;
    void perform("mcp", async () => {
      const result = await api.runMcpDemo(project.id);
      setDemoResult(result);
      await loadProject(project);
      setTab("activity");
      setNotice("The official MCP client called recall_project_memory and logged the result.");
    });
  }

  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setNotice("Copied to clipboard.");
    } catch {
      setError("Clipboard unavailable. Select and copy the snippet manually.");
    }
  }

  const filteredMemories = useMemo(() => {
    const query = search.trim().toLowerCase();
    return memories.filter((memory) => {
      const matchesType = !typeFilter || memory.type === typeFilter;
      const haystack = [memory.text, memory.type, ...(memory.tags || [])].join(" ").toLowerCase();
      return matchesType && (!query || haystack.includes(query));
    });
  }, [memories, search, typeFilter]);

  const latestRecall = events.find((event) => event.event_type === "recalled");
  const latestMcpRecall = activities.find(
    (activity) => activity.tool_name === "projectpulse.recall_project_memory"
  );
  const latestResult = activities.find((activity) => activity.kind === "agent_result");
  const recalledEvidence = latestMcpRecall?.evidence || demoResult?.memories || [];
  const status = project?.memory_mode === "demo"
    ? "Demo mode"
    : project?.memory_mode === "hindsight"
      ? "Hindsight connected"
      : health?.hindsight_configured
        ? "Hindsight connected"
        : "Demo mode";
  const isDemo = project?.memory_mode === "demo" || !health?.hindsight_configured;
  const instructionSnippet =
    "ProjectPulse project ID: " + (project?.id || "<PROJECT_ID>") + "\n\n" +
    "Before implementing a coding task, call recall_project_memory with the task description and follow relevant returned memories.\n" +
    "After resolving a durable engineering decision, incident, convention, or API contract, call retain_project_memory.\n" +
    "Never retain secrets, API keys, passwords, or personal data.";
  const config = target === "Claude Code"
    ? JSON.stringify({
        mcpServers: {
          projectpulse: {
            type: "stdio",
            command: ROOT_PLACEHOLDER + "/backend/.venv/bin/python",
            args: [ROOT_PLACEHOLDER + "/projectpulse-mcp/server.py"],
          },
        },
      }, null, 2)
    : JSON.stringify({
        servers: {
          projectpulse: {
            type: "stdio",
            command: ROOT_PLACEHOLDER + "/backend/.venv/bin/python",
            args: [ROOT_PLACEHOLDER + "/projectpulse-mcp/server.py"],
          },
        },
      }, null, 2);

  return (
    <main>
      <header>
        <div className="brand">
          <span className="logo">{"\u2726"}</span>
          <span>Project<span>Pulse</span></span>
          <em>Cross-agent engineering memory</em>
        </div>
        <div className="head-actions">
          <span className={"live " + (isDemo ? "setup" : "")}>
            <i /> {status.toUpperCase()}
          </span>
          <button className="ghost" onClick={() => setModal("project")}>+ New project</button>
        </div>
      </header>

      <section className="topbar">
        <div>
          <p className="eyebrow">PROJECT MEMORY BANK</p>
          <select
            aria-label="Project"
            value={project?.id || ""}
            onChange={(event) => {
              const next = projects.find((item) => item.id === event.target.value);
              if (next) openProject(next);
            }}
          >
            <option value="" disabled>Select a project</option>
            {projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </div>
        {project ? (
          <div className="bank">
            <span>{project.memory_mode === "demo"
              ? "Demo mode - local sample memory"
              : "Hindsight bank assigned - project isolated"}</span>
            <code>{project.hindsight_bank_id}</code>
          </div>
        ) : (
          <button className="primary" onClick={launchDemo} disabled={!!busy}>
            {busy === "demo" ? "Preparing demo..." : "Launch E-commerce MCP demo"}
          </button>
        )}
      </section>

      {error && (
        <div className="error" role="alert">
          <span>{error}</span>
          <div className="error-actions">
            {retry && <button onClick={retry} disabled={!!busy}>Retry</button>}
            <button aria-label="Dismiss error" onClick={() => setError("")}>x</button>
          </div>
        </div>
      )}
      {notice && <div className="notice" role="status">{notice}</div>}

      {!project ? (
        <section className="empty">
          <div className="empty-icon">{"\u2311"}</div>
          <p className="eyebrow">MCP-FIRST ENGINEERING MEMORY</p>
          <h1>Persistent project memory for coding agents.</h1>
          <p>
            ProjectPulse connects your coding agent to a project-scoped Hindsight memory bank.
            New sessions recall the decisions that matter before they write code.
          </p>
          <div className="landing-actions">
            <button className="primary big" onClick={launchDemo} disabled={!!busy}>
              {busy === "demo" ? "Preparing demo..." : "Launch E-commerce MCP demo"}
            </button>
            <button className="ghost big" onClick={() => setModal("project")}>
              Create project
            </button>
          </div>
          {isDemo && <p className="mode-note">Demo mode - local sample memory. Add a Hindsight key for real cloud memory.</p>}
        </section>
      ) : (
        <>
          <section className="hero">
            <div>
              <p className="eyebrow">{project.name}</p>
              <h1>{project.description || "An isolated engineering memory bank for this project."}</h1>
              <p className="sub">
                This dashboard manages evidence. Coding agents use ProjectPulse through MCP.
              </p>
            </div>
            <div className="hero-actions">
              {project.name === "E-commerce Platform" && (
                <button className="ghost" onClick={launchDemo} disabled={!!busy}>
                  {busy === "demo" ? "Seeding..." : "Seed demo data"}
                </button>
              )}
              <button className="secondary" onClick={() => setModal("memory")}>
                + Retain memory
              </button>
            </div>
          </section>

          <nav className="section-nav" aria-label="Dashboard sections">
            {([
              ["overview", "Overview"],
              ["timeline", "Memory timeline"],
              ["activity", "Agent activity"],
              ["setup", "MCP setup"],
            ] as [Tab, string][]).map(([key, label]) => (
              <button
                key={key}
                className={tab === key ? "active" : ""}
                onClick={() => setTab(key)}
              >{label}</button>
            ))}
          </nav>

          {tab === "overview" && (
            <section className="tab-content">
              <div className="overview-grid">
                <article className="panel emphasis">
                  <p className="eyebrow">MEMORY CONNECTION</p>
                  <h2>{project.memory_mode === "demo" ? "Demo mode" : "Hindsight connected"}</h2>
                  <p>{project.memory_mode === "demo"
                    ? "Local sample memory is isolated to this project. It is not Hindsight."
                    : "Retain, Recall, and List use this project's Hindsight Cloud bank."}</p>
                  <code>{project.hindsight_bank_id}</code>
                </article>
                <article className="panel number-panel">
                  <p className="eyebrow">RETAINED MEMORIES</p>
                  <strong>{memories.length}</strong>
                  <p>Inspectable facts in the selected project bank.</p>
                </article>
                <article className="panel">
                  <p className="eyebrow">LATEST RECALL</p>
                  {latestRecall ? (
                    <>
                      <h3>{latestRecall.agent_name || "Coding agent"}</h3>
                      <p>{latestRecall.source_text}</p>
                      <small>{timeLabel(latestRecall.created_at)}</small>
                    </>
                  ) : <p>No recall yet. Start the MCP demo to create an audit event.</p>}
                </article>
              </div>
              <div className="feature-strip">
                <div>
                  <p className="eyebrow">JUDGE-FACING PROOF</p>
                  <h2>See the actual MCP call.</h2>
                  <p>
                    Run a fresh local Agent B session. The official MCP client calls
                    <code> recall_project_memory</code>, and this dashboard shows the exact evidence.
                  </p>
                </div>
                <button className="primary" onClick={runMcpDemo} disabled={!!busy}>
                  {busy === "mcp" ? "Calling MCP tool..." : "Run fresh Agent B MCP demo"}
                </button>
              </div>
            </section>
          )}

          {tab === "timeline" && (
            <section className="tab-content">
              <div className="section-title">
                <div>
                  <p className="eyebrow">PROJECT KNOWLEDGE</p>
                  <h2>Memory timeline</h2>
                  <p className="sub">Each fact is scoped to this project's bank.</p>
                </div>
                <button className="secondary" onClick={() => setModal("memory")}>+ Retain memory</button>
              </div>
              <div className="filter-row">
                <input
                  aria-label="Search memories"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search memory text or tags"
                />
                <select
                  aria-label="Filter memory type"
                  value={typeFilter}
                  onChange={(event) => setTypeFilter(event.target.value)}
                >
                  <option value="">All memory types</option>
                  <option value="security_rule">Security rule</option>
                  <option value="api_contract">API contract</option>
                  <option value="architecture_decision">Architecture decision</option>
                  <option value="incident_fix">Incident fix</option>
                  <option value="coding_convention">Coding convention</option>
                </select>
                <span>{filteredMemories.length} shown</span>
              </div>
              {filteredMemories.length ? (
                <ol className="memory-list">
                  {filteredMemories.map((memory) => (
                    <li key={memory.id}>
                      <button onClick={() => setSelectedMemory(memory)}>
                        <div className="memory-list-head">
                          <span className="type-pill">{kindLabel(memory.type)}</span>
                          <time>{timeLabel(memory.timestamp)}</time>
                        </div>
                        <p>{memory.text}</p>
                        <div className="memory-list-meta">
                          <span>{memory.source_agent || memory.metadata.source_agent || "Project agent"}</span>
                          <span>{memory.session_id ? "Session " + memory.session_id.slice(0, 8) : "Session unavailable"}</span>
                          <span>{memory.origin === "demo" ? "Demo mode - local sample memory" : "Retained through Hindsight"}</span>
                        </div>
                        <div className="tag-list">{(memory.tags || []).filter((tag) => !tag.startsWith("project:")).map(
                          (tag) => <span key={tag}>#{tag}</span>
                        )}</div>
                      </button>
                    </li>
                  ))}
                </ol>
              ) : (
                <div className="empty-panel">
                  {memories.length ? "No memories match this filter." : "No memories yet. Retain a fact or seed the E-commerce demo."}
                </div>
              )}
              <div className="audit-mini">
                <div className="section-title">
                  <h3>Retain and recall audit</h3>
                  <button className="ghost" onClick={() => void perform("refresh", () => loadProject(project))}>Refresh</button>
                </div>
                {events.length ? events.map((event) => (
                  <div key={event.id} className="audit-mini-row">
                    <span className={"dot " + event.event_type} />
                    <span>{event.agent_name || "An agent"} {event.event_type === "retained" ? "retained" : "recalled"}: {eventText(event)}</span>
                    <time>{timeLabel(event.created_at)}</time>
                  </div>
                )) : <p className="muted">No audit events yet.</p>}
              </div>
            </section>
          )}

          {tab === "activity" && (
            <section className="tab-content">
              <div className="section-title">
                <div>
                  <p className="eyebrow">REAL TOOL-CALL EVIDENCE</p>
                  <h2>Agent activity</h2>
                  <p className="sub">This is an MCP activity viewer, not a coding-agent interface.</p>
                </div>
                <div className="hero-actions">
                  <button className="ghost" onClick={() => void perform("refresh", () => loadProject(project))}>Refresh</button>
                  <button className="primary" onClick={runMcpDemo} disabled={!!busy}>
                    {busy === "mcp" ? "Calling MCP..." : "Run fresh Agent B MCP demo"}
                  </button>
                </div>
              </div>
              <div className="activity-layout">
                <div className="activity-stream">
                  {activities.length ? [...activities].reverse().map((item, index) => (
                    <article key={item.id} className={"activity-item " + item.kind}>
                      <span className="step-index">{String(index + 1).padStart(2, "0")}</span>
                      <div>
                        <div className="activity-title">
                          <span>{item.kind === "session_started" ? "Fresh Agent B session started"
                            : item.kind === "task" ? "User task"
                            : item.kind === "tool_call" ? item.tool_name || "Tool call"
                            : item.kind === "recall_evidence" ? "Recalled evidence"
                            : item.kind === "agent_result" ? "Local sample agent result"
                            : kindLabel(item.kind)}</span>
                          <time>{timeLabel(item.created_at)}</time>
                        </div>
                        <p>{item.summary}</p>
                        <small>{item.agent_name || "ProjectPulse"} | {item.origin === "demo"
                          ? "Demo mode - local sample memory"
                          : "Hindsight"}</small>
                      </div>
                    </article>
                  )) : (
                    <div className="empty-panel">
                      No agent activity yet. Run the MCP demo or connect a coding agent in MCP setup.
                    </div>
                  )}
                </div>
                <aside className="proof-panel">
                  <p className="eyebrow">WHY THIS ANSWER IS PROJECT-AWARE</p>
                  <h3>Exact recalled memory</h3>
                  {recalledEvidence.length ? recalledEvidence.map((memory) => (
                    <div className="proof-memory" key={memory.id}>
                      <span className="type-pill">{kindLabel(memory.type)}</span>
                      <p>{memory.text}</p>
                      <small>{memory.source_agent || memory.metadata.source_agent || "Project agent"}
                        {" | "}{timeLabel(memory.timestamp)}</small>
                    </div>
                  )) : <p className="muted">Run the fresh Agent B MCP demo to see the evidence.</p>}
                  {latestResult && (
                    <div className="sample-result">
                      <strong>Result after recall</strong>
                      <p>{latestResult.summary}</p>
                    </div>
                  )}
                  {demoResult && <small>Actual call: {demoResult.tool_call}</small>}
                </aside>
              </div>
            </section>
          )}

          {tab === "setup" && (
            <section className="tab-content">
              <div className="section-title">
                <div>
                  <p className="eyebrow">CONNECT YOUR CODING AGENT</p>
                  <h2>MCP setup</h2>
                  <p className="sub">The coding agent calls these tools; this dashboard only manages evidence.</p>
                </div>
              </div>
              <div className="setup-grid">
                <div className="panel">
                  <label>
                    Coding-agent target
                    <select value={target} onChange={(event) => setTarget(event.target.value as Target)}>
                      <option>Claude Code</option>
                      <option>GitHub Copilot</option>
                    </select>
                  </label>
                  <p className="setup-hint">
                    {target === "Claude Code"
                      ? "Save this as .mcp.json in the coding project's root."
                      : "Save this as .vscode/mcp.json in the VS Code workspace."}
                    {" "}Replace <code>{ROOT_PLACEHOLDER}</code> with the absolute path to this ProjectPulse checkout.
                  </p>
                  <div className="code-head"><span>MCP server configuration</span><button className="ghost" onClick={() => void copy(config)}>Copy</button></div>
                  <pre>{config}</pre>
                </div>
                <div className="panel">
                  <p className="eyebrow">PROJECT INSTRUCTIONS</p>
                  <p className="setup-hint">
                    Put this in the coding project's {target === "Claude Code"
                      ? "CLAUDE.md" : ".github/copilot-instructions.md"}.
                    MCP tools do not run automatically.
                  </p>
                  <div className="code-head"><span>Agent instructions</span><button className="ghost" onClick={() => void copy(instructionSnippet)}>Copy</button></div>
                  <pre>{instructionSnippet}</pre>
                  <p className="setup-hint">Project ID: <code>{project.id}</code></p>
                </div>
              </div>
              <div className="setup-footer">
                <strong>Available tools</strong>
                <span>recall_project_memory</span>
                <span>retain_project_memory</span>
                <span>list_project_memories</span>
              </div>
            </section>
          )}
        </>
      )}

      {modal === "project" && <ProjectModal
        close={() => setModal(null)}
        save={createProject}
        saving={busy === "project"}
        error={error}
      />}
      {modal === "memory" && <MemoryModal
        close={() => setModal(null)}
        save={retainMemory}
        saving={busy === "retain"}
        error={error}
        showExample={project?.name === "E-commerce Platform"}
        demo={project?.memory_mode === "demo"}
      />}
      {selectedMemory && <MemoryDetail
        memory={selectedMemory}
        close={() => setSelectedMemory(null)}
      />}
    </main>
  );
}

function ProjectModal({
  close, save, saving, error,
}: {
  close: () => void;
  save: (data: { name: string; description: string }) => void;
  saving: boolean;
  error: string;
}) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    save({
      name: String(form.get("name") || ""),
      description: String(form.get("description") || ""),
    });
  };
  return <div className="overlay">
    <form className="modal" onSubmit={submit}>
      <button type="button" className="close" onClick={close} aria-label="Close dialog">x</button>
      <p className="eyebrow">NEW PROJECT</p>
      <h2>Create an isolated memory bank</h2>
      <label>Project name<input name="name" required minLength={2} placeholder="Mobile Banking App" /></label>
      <label>Description<textarea name="description" placeholder="What will coding agents build?" /></label>
      {error && <p className="modal-error">{error}</p>}
      <button className="primary" disabled={saving}>
        {saving ? "Creating..." : "Create project"}
      </button>
    </form>
  </div>;
}

function MemoryModal({
  close, save, saving, error, showExample, demo,
}: {
  close: () => void;
  save: (data: MemoryForm) => void;
  saving: boolean;
  error: string;
  showExample: boolean;
  demo: boolean;
}) {
  const [kind, setKind] = useState<MemoryForm["memory_type"]>("security_rule");
  const [content, setContent] = useState("");
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    save({
      memory_type: kind,
      source_agent: String(form.get("agent") || ""),
      content,
      tags: String(form.get("tags") || "").split(",").map((tag) => tag.trim()).filter(Boolean),
    });
  };
  return <div className="overlay">
    <form className="modal" onSubmit={submit}>
      <button type="button" className="close" onClick={close} aria-label="Close dialog">x</button>
      <p className="eyebrow">RETAIN ENGINEERING LEARNING</p>
      <h2>Give the next agent a useful head start.</h2>
      <label>Memory type
        <select value={kind} onChange={(event) => setKind(event.target.value as MemoryForm["memory_type"])}>
          <option value="architecture_decision">Architecture decision</option>
          <option value="security_rule">Security rule</option>
          <option value="api_contract">API contract</option>
          <option value="incident_fix">Incident fix</option>
          <option value="coding_convention">Coding convention</option>
        </select>
      </label>
      <label>Source agent<input name="agent" defaultValue="Agent A - previous session" required /></label>
      <label>Tags, comma-separated<input name="tags" placeholder="authentication, security" /></label>
      <label>What should future agents remember?
        <textarea
          value={content}
          onChange={(event) => setContent(event.target.value)}
          rows={5}
          minLength={12}
          required
          placeholder="State the decision, why it matters, and what to avoid."
        />
      </label>
      {showExample && <button type="button" className="example-button" onClick={() => setContent(JWT_EXAMPLE)}>
        Use JWT demo decision
      </button>}
      <p className="form-footnote">Never retain secrets, API keys, passwords, or personal data.</p>
      {error && <p className="modal-error">{error}</p>}
      <button className="primary" disabled={saving}>
        {saving ? "Saving..." : demo ? "Retain in Demo mode" : "Retain through Hindsight"}
      </button>
    </form>
  </div>;
}

function MemoryDetail({ memory, close }: { memory: Memory; close: () => void }) {
  return <div className="overlay">
    <div className="modal detail-modal" role="dialog" aria-modal="true" aria-label="Memory details">
      <button className="close" onClick={close} aria-label="Close memory details">x</button>
      <p className="eyebrow">PROJECT MEMORY DETAIL</p>
      <span className="type-pill">{kindLabel(memory.type)}</span>
      <h2>{memory.text}</h2>
      <div className="detail-grid">
        <div><small>Source agent</small><strong>{memory.source_agent || memory.metadata.source_agent || "Unknown"}</strong></div>
        <div><small>Session</small><strong>{memory.session_id || "Unavailable"}</strong></div>
        <div><small>Retained</small><strong>{timeLabel(memory.timestamp)}</strong></div>
        <div><small>Storage</small><strong>{memory.origin === "demo" ? "Demo mode - local sample memory" : "Hindsight"}</strong></div>
      </div>
      <div className="tag-list">{(memory.tags || []).map((tag) => <span key={tag}>#{tag}</span>)}</div>
      <small className="memory-id">Memory ID: {memory.id}</small>
    </div>
  </div>;
}



