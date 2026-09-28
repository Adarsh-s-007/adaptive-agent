import { FormEvent, useEffect, useState } from "react";
import { api, Answer, Event, Health, MemoryForm, Project, Stats } from "./api";

const AUTH_TASK = "Build the login screen and authentication flow.";
const JWT_EXAMPLE =
  "JWT refresh tokens must be stored in HTTP-only cookies. Never use localStorage because it increases XSS exposure.";
const EMPTY_STATS: Stats = { retained: 0, recalled: 0, decisions: 0, bug_fixes: 0 };

function timeLabel(value: string): string {
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

function retainedParts(text: string): { kind: string; content: string; agent: string } {
  const kind = text.match(/^Memory type: (.+)$/m)?.[1] || "project learning";
  const agent = text.match(/^Source agent: (.+)$/m)?.[1] || "Agent A";
  const content = text.split("Decision / learning: ")[1] || text;
  return { kind, content, agent };
}

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [stats, setStats] = useState<Stats>(EMPTY_STATS);
  const [health, setHealth] = useState<Health | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [task, setTask] = useState(AUTH_TASK);
  const [agent, setAgent] = useState("Agent B - fresh session");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [retry, setRetry] = useState<(() => void) | null>(null);
  const [modal, setModal] = useState<"project" | "memory" | null>(null);

  async function loadProject(next: Project) {
    const [nextEvents, nextStats] = await Promise.all([
      api.timeline(next.id),
      api.stats(next.id),
    ]);
    setProject(next);
    setEvents(nextEvents);
    setStats(nextStats);
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
    setAnswer(null);
    void perform("refresh", async () => {
      await loadProject(next);
    });
  }

  function launchDemo() {
    void perform("demo", async () => {
      const latest = await api.projects();
      let demo = latest.find((item) => item.name === "E-commerce Platform");
      if (!demo) {
        demo = await api.createProject({
          name: "E-commerce Platform",
          description:
            "Shared engineering memory for storefront, payments, and authentication.",
        });
      }
      const result = await api.seed(demo.id);
      setProjects(await api.projects());
      setAnswer(null);
      await loadProject(demo);
      setNotice(
        result.seeded
          ? "Agent A retained " + result.seeded + " demo memories in Hindsight."
          : "The E-commerce demo is ready. Its seed memories were already retained."
      );
    });
  }

  function createProject(data: { name: string; description: string }) {
    void perform("project", async () => {
      const created = await api.createProject(data);
      setProjects(await api.projects());
      await loadProject(created);
      setAnswer(null);
      setModal(null);
      setNotice("Project created with its own Hindsight bank.");
    });
  }

  function retainMemory(data: MemoryForm) {
    if (!project) return;
    void perform("retain", async () => {
      await api.retain(project.id, data);
      await loadProject(project);
      setModal(null);
      setNotice(data.source_agent + " retained a project memory in Hindsight.");
    });
  }

  function ask() {
    if (!project || !task.trim()) return;
    void perform("ask", async () => {
      setAnswer(null);
      const nextAnswer = await api.ask(project.id, {
        agent_name: agent,
        task: task.trim(),
      });
      setAnswer(nextAnswer);
      await loadProject(project);
    });
  }

  const configured = health?.hindsight_configured && health?.groq_configured;

  return (
    <main>
      <header>
        <div className="brand">
          <span className="logo">✦</span>
          <span>
            Project<span>Pulse</span>
          </span>
          <em>Cross-agent engineering memory</em>
        </div>
        <div className="head-actions">
          <span className={"live " + (configured ? "" : "setup")}>
            <i /> {health ? (configured ? "KEYS CONFIGURED" : "SETUP REQUIRED") : "CHECKING SETUP"}
          </span>
          <button className="ghost" onClick={() => setModal("project")}>
            + New project
          </button>
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
            <option value="" disabled>
              Select a project
            </option>
            {projects.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        {project ? (
          <div className="bank">
            <span>Hindsight bank assigned · project isolated</span>
            <code>{project.hindsight_bank_id}</code>
          </div>
        ) : (
          <button className="primary" onClick={launchDemo} disabled={!!busy}>
            {busy === "demo" ? "Preparing demo…" : "Launch E-commerce demo"}
          </button>
        )}
      </section>

      {error && (
        <div className="error" role="alert">
          <span>{error}</span>
          <div className="error-actions">
            {retry && (
              <button onClick={retry} disabled={!!busy}>
                Retry
              </button>
            )}
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              ×
            </button>
          </div>
        </div>
      )}
      {notice && <div className="notice" role="status">{notice}</div>}

      {!project ? (
        <section className="empty">
          <div className="empty-icon">⌁</div>
          <h1>A memory layer for every engineering agent.</h1>
          <p>
            Create a project or launch the E-commerce demo. Fresh sessions receive only
            relevant project learning before they answer.
          </p>
          <button className="primary big" onClick={launchDemo} disabled={!!busy}>
            {busy === "demo" ? "Preparing memory bank…" : "Launch E-commerce demo"}
          </button>
        </section>
      ) : (
        <>
          <section className="hero">
            <div>
              <p className="eyebrow">{project.name}</p>
              <h1>{project.description || "A dedicated memory bank for this project."}</h1>
              <p className="sub">
                One project bank. Task-specific recall. A clear audit of what agents learned.
              </p>
            </div>
            <div className="hero-actions">
              {project.name === "E-commerce Platform" && (
                <button className="ghost" onClick={launchDemo} disabled={!!busy}>
                  {busy === "demo" ? "Seeding…" : "Seed demo data"}
                </button>
              )}
              <button className="secondary" onClick={() => setModal("memory")}>
                ＋ Retain learning
              </button>
            </div>
          </section>

          <section className="metrics" aria-label="Project memory statistics">
            <Metric value={stats.retained} label="Retained learning" />
            <Metric value={stats.decisions} label="Architecture decisions" />
            <Metric value={stats.bug_fixes} label="Bug fixes" />
            <Metric value={stats.recalled} label="Recall events" />
          </section>

          <section className="workspace">
            <div className="workspace-head">
              <div>
                <p className="eyebrow">AGENT WORKSPACE</p>
                <h2>Prove the memory difference.</h2>
              </div>
              <span className="fresh">
                ◉ {agent.includes("Agent B") ? "Fresh session · no prior chat" : "Previous session"}
              </span>
            </div>
            <div className="controls">
              <label>
                Who is working?
                <select value={agent} onChange={(event) => setAgent(event.target.value)}>
                  <option>Agent A - previous session</option>
                  <option>Agent B - fresh session</option>
                </select>
              </label>
              <label className="task">
                Current engineering task
                <textarea
                  value={task}
                  onChange={(event) => setTask(event.target.value)}
                  rows={2}
                  placeholder="Describe the work this agent needs to do"
                />
              </label>
              <button
                className="primary ask"
                disabled={!!busy || !task.trim()}
                onClick={ask}
              >
                {busy === "ask" ? "Recalling memories…" : "Ask ProjectPulse →"}
              </button>
            </div>
            {answer ? (
              <Answers answer={answer} />
            ) : (
              <div className="comparison-placeholder">
                <div>
                  <span>01</span>
                  <b>Generic AI</b>
                  <p>General guidance without previous project decisions.</p>
                </div>
                <div>
                  <span>02</span>
                  <b>With Hindsight</b>
                  <p>Relevant decisions retrieved before the agent responds.</p>
                </div>
              </div>
            )}
          </section>

          <section className="timeline">
            <div className="section-title">
              <div>
                <p className="eyebrow">AUDIT TRAIL</p>
                <h2>Project memory timeline</h2>
              </div>
              <button className="ghost" onClick={() => openProject(project)} disabled={!!busy}>
                ↻ Refresh
              </button>
            </div>
            {events.length ? (
              <ol>
                {events.map((event) => {
                  const retained = retainedParts(event.source_text);
                  return (
                    <li key={event.id}>
                      <span className={"dot " + event.event_type} />
                      <div>
                        <b>
                          {event.event_type === "retained"
                            ? retained.agent + " retained " + retained.kind
                            : (event.agent_name || "An agent") + " recalled project memory"}
                        </b>
                        <p>
                          {event.event_type === "retained"
                            ? retained.content
                            : "Task: " + event.source_text}
                        </p>
                      </div>
                      <time>{timeLabel(event.created_at)}</time>
                    </li>
                  );
                })}
              </ol>
            ) : (
              <div className="muted">
                No memory events yet. Retain a decision or seed the E-commerce demo.
              </div>
            )}
          </section>
        </>
      )}

      {modal === "project" && (
        <ProjectModal
          close={() => setModal(null)}
          save={createProject}
          saving={busy === "project"}
          error={error}
        />
      )}
      {modal === "memory" && (
        <MemoryModal
          close={() => setModal(null)}
          save={retainMemory}
          saving={busy === "retain"}
          error={error}
          showExample={project?.name === "E-commerce Platform"}
        />
      )}
    </main>
  );
}

function Metric({ value, label }: { value: number; label: string }) {
  return (
    <div className="metric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function Answers({ answer }: { answer: Answer }) {
  const count = answer.memories.length;
  return (
    <>
      <div className="memory-callout">
        <span>✦</span>
        <div>
          <b>
            This answer used {count} relevant project {count === 1 ? "memory" : "memories"}.
          </b>
          <p>
            {count
              ? "Retrieved from this project's Hindsight bank: "
              : "No task-relevant learning was found in this project bank."}
            {count > 0 && <code>{answer.used_bank_id}</code>}
          </p>
        </div>
      </div>
      <div className="answers">
        <article className="generic">
          <div className="answer-label">WITHOUT PROJECT MEMORY</div>
          <h3>Generic AI response</h3>
          <p>{answer.generic_answer}</p>
        </article>
        <article className="aware">
          <div className="answer-label">✦ HINDSIGHT RECALL APPLIED</div>
          <h3>With project memory</h3>
          <p>{answer.memory_aware_answer}</p>
        </article>
      </div>
      <aside className="evidence">
        <div>
          <p className="eyebrow">RECALLED MEMORY EVIDENCE</p>
          <h3>What the fresh agent was given</h3>
        </div>
        {count ? (
          answer.memories.map((memory) => (
            <div className="memory" key={memory.id}>
              <span>{memory.metadata.memory_type || memory.type}</span>
              <p>{memory.text}</p>
              <footer>
                {memory.metadata.source_agent || "Project memory"}
                {" · "}
                {memory.timestamp ? timeLabel(memory.timestamp) : "Date unavailable"}
                {" · "}
                {memory.why_relevant || "Matched this engineering task"}
              </footer>
              {memory.source_text && memory.source_text !== memory.text && (
                <details>
                  <summary>Original retained context</summary>
                  <p>{memory.source_text}</p>
                </details>
              )}
            </div>
          ))
        ) : (
          <p className="muted">No retained decision was relevant to this task.</p>
        )}
      </aside>
    </>
  );
}

function ProjectModal({
  close,
  save,
  saving,
  error,
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
  return (
    <div className="overlay">
      <form className="modal" onSubmit={submit}>
        <button type="button" className="close" onClick={close} aria-label="Close dialog">
          ×
        </button>
        <p className="eyebrow">NEW PROJECT</p>
        <h2>Create an isolated memory bank</h2>
        <label>
          Project name
          <input name="name" required minLength={2} placeholder="Mobile Banking App" />
        </label>
        <label>
          Description
          <textarea name="description" placeholder="What will agents build?" />
        </label>
        {error && <p className="modal-error">{error}</p>}
        <button className="primary" disabled={saving}>
          {saving ? "Creating bank…" : "Create project + Hindsight bank"}
        </button>
      </form>
    </div>
  );
}

function MemoryModal({
  close,
  save,
  saving,
  error,
  showExample,
}: {
  close: () => void;
  save: (data: MemoryForm) => void;
  saving: boolean;
  error: string;
  showExample: boolean;
}) {
  const [kind, setKind] = useState<MemoryForm["memory_type"]>("architecture decision");
  const [content, setContent] = useState("");
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    save({
      memory_type: kind,
      source_agent: String(form.get("agent") || ""),
      content,
    });
  };
  return (
    <div className="overlay">
      <form className="modal" onSubmit={submit}>
        <button type="button" className="close" onClick={close} aria-label="Close dialog">
          ×
        </button>
        <p className="eyebrow">RETAIN LEARNING · AGENT A</p>
        <h2>Give the next agent a useful head start.</h2>
        <label>
          Memory type
          <select
            value={kind}
            onChange={(event) => setKind(event.target.value as MemoryForm["memory_type"])}
          >
            <option>architecture decision</option>
            <option>coding convention</option>
            <option>bug fix</option>
            <option>failed approach</option>
            <option>feature progress</option>
          </select>
        </label>
        <label>
          Source agent
          <input name="agent" defaultValue="Agent A - previous session" required />
        </label>
        <label>
          What should future agents remember?
          <textarea
            value={content}
            onChange={(event) => setContent(event.target.value)}
            rows={5}
            minLength={12}
            required
            placeholder="State the decision, why it matters, and what to avoid."
          />
        </label>
        {showExample && (
          <button
            type="button"
            className="example-button"
            onClick={() => {
              setKind("architecture decision");
              setContent(JWT_EXAMPLE);
            }}
          >
            Use JWT demo decision
          </button>
        )}
        {error && <p className="modal-error">{error}</p>}
        <button className="primary" disabled={saving}>
          {saving ? "Retaining in Hindsight…" : "Retain in Hindsight"}
        </button>
      </form>
    </div>
  );
}
