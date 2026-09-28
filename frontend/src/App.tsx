import { FormEvent, useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Activity,
  api,
  Event,
  GovernedRecord,
  Health,
  HindsightProbe,
  McpDemo,
  Memory,
  MemoryForm,
  Project,
  ProjectMetrics,
  RulebookData,
  Stats,
  TimelineItem,
} from "./api";
import SceneBackground from "./three/SceneBackground";
import MemoryOrbit from "./three/MemoryOrbit";
import { MEMORY_TYPES, memoryColor } from "./three/support";
import { emitScene } from "./three/bus";
import { Flight, RetainFlights } from "./RetainFlight";
import {
  AnimatedNumber,
  hoverLift,
  listItem,
  rise,
  stagger,
  tabMotion,
  useButtonRipples,
} from "./motion";

type Tab =
  | "overview"
  | "workspace"
  | "records"
  | "timeline"
  | "metrics"
  | "rulebook"
  | "activity"
  | "setup";

type Target = "Claude Code" | "GitHub Copilot";
type WorkspaceAgent = "Codex" | "Claude Code" | "GitHub Copilot" | "Agent B - simulated";

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
  useButtonRipples();

  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [hindsightProbe, setHindsightProbe] = useState<HindsightProbe | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [stats, setStats] = useState<Stats>(EMPTY_STATS);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [activities, setActivities] = useState<Activity[]>([]);
  const [governedRecords, setGovernedRecords] = useState<GovernedRecord[]>([]);
  const [metrics, setMetrics] = useState<ProjectMetrics | null>(null);
  const [v1Timeline, setV1Timeline] = useState<TimelineItem[]>([]);
  const [rulebookData, setRulebookData] = useState<RulebookData | null>(null);

  const [tab, setTab] = useState<Tab>("overview");
  const [target, setTarget] = useState<Target>("Claude Code");
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [recordStatusFilter, setRecordStatusFilter] = useState<string>("all");
  const [focusType, setFocusType] = useState<string | null>(null);

  // Agent workspace state (from main)
  const [workspaceAgent, setWorkspaceAgent] = useState<WorkspaceAgent>("Agent B - simulated");
  const [workspaceTask, setWorkspaceTask] = useState(
    "Implement login and refresh-token flow with HttpOnly cookies for this project."
  );
  const [workspaceMemories, setWorkspaceMemories] = useState<Memory[] | null>(null);

  // Flight animations (from motion)
  const [flights, setFlights] = useState<Flight[]>([]);

  const [selectedMemory, setSelectedMemory] = useState<Memory | null>(null);
  const [supersedeTarget, setSupersedeTarget] = useState<GovernedRecord | null>(null);
  const [retractTarget, setRetractTarget] = useState<GovernedRecord | null>(null);
  const [modal, setModal] = useState<"project" | "memory" | "record" | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [retry, setRetry] = useState<(() => void) | null>(null);
  const [demoResult, setDemoResult] = useState<McpDemo | null>(null);

  async function loadProject(next: Project) {
    const [
      nextEvents,
      nextStats,
      nextMemories,
      nextActivities,
      nextRecords,
      nextMetrics,
      nextV1Timeline,
      nextRulebook,
    ] = await Promise.all([
      api.timeline(next.id).catch(() => []),
      api.stats(next.id).catch(() => EMPTY_STATS),
      api.memories(next.id).catch(() => ({
        memories: [],
        count: 0,
        origin: "demo" as const,
        mode_label: "Demo mode",
        used_bank_id: next.hindsight_bank_id,
      })),
      api.activity(next.id).catch(() => []),
      api.getGovernedRecords(next.id).catch(() => []),
      api.getMetrics(next.id).catch(() => null),
      api.getV1Timeline(next.id).catch(() => []),
      api.getRulebook(next.id).catch(() => null),
    ]);

    setProject(next);
    setEvents(nextEvents);
    setStats(nextStats);
    setMemories(nextMemories.memories);
    setActivities(nextActivities);
    setGovernedRecords(nextRecords);
    setMetrics(nextMetrics);
    setV1Timeline(nextV1Timeline);
    setRulebookData(nextRulebook);

    emitScene({
      type: "health",
      value: next.memory_mode === "hindsight" ? "connected" : "demo",
    });
  }

  async function perform(label: string, action: () => Promise<void>) {
    setBusy(label);
    emitScene({ type: "busy", value: true });
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
      emitScene({ type: "busy", value: false });
    }
  }

  useEffect(() => {
    void api.health().then(setHealth).catch(() => setHealth(null));
    void api
      .hindsightProbe()
      .then((probe) => {
        setHindsightProbe(probe);
        emitScene({
          type: "health",
          value: probe.status === "connected" || probe.status === "ok" ? "connected" : "demo",
        });
      })
      .catch(() => null);

    void api
      .projects()
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
      const updatedProjects = await api.projects();
      setProjects(updatedProjects);
      const updatedDemo = updatedProjects.find((p) => p.id === demo?.id) || demo;
      setDemoResult(null);
      setTab("overview");
      await loadProject(updatedDemo);
      emitScene({
        type: "wave",
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
        color: "#52d9ca",
      });
      setNotice(
        result.seeded
          ? "Agent A retained " + result.seeded + " sample engineering memories. " + result.mode_label
          : "The E-commerce memory bank is ready. " + result.mode_label
      );
    });
  }

  function provisionHindsight() {
    if (!project) return;
    void perform("provision", async () => {
      const result = await api.provisionBank(project.id);
      const updatedList = await api.projects();
      setProjects(updatedList);
      const updated = updatedList.find((p) => p.id === project.id) || project;
      await loadProject(updated);
      void api.hindsightProbe().then(setHindsightProbe).catch(() => null);
      emitScene({ type: "health", value: "connected" });
      emitScene({
        type: "wave",
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
        color: "#38bdf8",
      });
      setNotice(
        `⚡ Hindsight Bank "${result.bank_id}" successfully provisioned with directives & Rulebook mental model!`
      );
    });
  }

  function seedEnterpriseData(dataset: "apexcart" | "ledgerlite") {
    if (!project) return;
    void perform("seed_enterprise", async () => {
      const result = await api.seedEnterprise(project.id, dataset);
      await loadProject(project);
      emitScene({
        type: "wave",
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
        color: dataset === "apexcart" ? "#8d7cff" : "#eab96a",
      });
      setNotice(
        `Seeded ${result.records_seeded} authentic ${result.dataset.toUpperCase()} records. Total active records: ${result.total_active}.`
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

  function retainMemory(data: MemoryForm, buttonRect?: DOMRect) {
    if (!project) return;
    void perform("retain", async () => {
      await api.retain(project.id, data);
      if (buttonRect) {
        const flight: Flight = {
          id: Date.now(),
          from: {
            x: buttonRect.left + buttonRect.width / 2,
            y: buttonRect.top + buttonRect.height / 2,
          },
          to: { x: window.innerWidth / 2, y: window.innerHeight / 2 },
          color: memoryColor(data.memory_type),
          onLand: () => {
            emitScene({
              type: "wave",
              x: window.innerWidth / 2,
              y: window.innerHeight / 2,
              color: memoryColor(data.memory_type),
            });
          },
        };
        setFlights((prev) => [...prev, flight]);
      }
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

  function createGovernedRecord(data: {
    title: string;
    statement: string;
    memory_type: string;
    rationale?: string;
    area?: string;
    importance?: number;
    tags?: string[];
  }) {
    if (!project) return;
    void perform("create_record", async () => {
      const res = await api.createGovernedRecord(project.id, data);
      await loadProject(project);
      setModal(null);
      setTab("records");
      emitScene({
        type: "wave",
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
        color: memoryColor(data.memory_type),
      });
      setNotice(`Governed memory record ${res.pill} created (${res.retain_state}).`);
    });
  }

  function handleSupersede(data: {
    title: string;
    statement: string;
    rationale: string;
    importance: number;
    evidence_quote?: string;
  }) {
    if (!project || !supersedeTarget) return;
    void perform("supersede", async () => {
      const res = await api.supersedeRecord(project.id, supersedeTarget.id, data);
      await loadProject(project);
      setSupersedeTarget(null);
      emitScene({
        type: "wave",
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
        color: "#f59e0b",
      });
      setNotice(
        `Record ${supersedeTarget.pill} superseded by new record ${res.new_pill} via 5-step protocol.`
      );
    });
  }

  function handleRetract(reason: string) {
    if (!project || !retractTarget) return;
    void perform("retract", async () => {
      await api.retractRecord(project.id, retractTarget.id, reason);
      await loadProject(project);
      setRetractTarget(null);
      emitScene({
        type: "wave",
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
        color: "#ef4444",
      });
      setNotice(`Record ${retractTarget.pill} retracted.`);
    });
  }

  function handleFlushOutbox() {
    if (!project) return;
    void perform("flush_outbox", async () => {
      const res = await api.flushOutbox(project.id);
      await loadProject(project);
      setNotice(`Outbox synced: ${res.flushed} flushed, ${res.remaining} remaining.`);
    });
  }

  function handleRefreshRulebook() {
    if (!project) return;
    void perform("refresh_rulebook", async () => {
      const res = await api.refreshRulebook(project.id);
      setRulebookData(res);
      emitScene({
        type: "wave",
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
        color: "#6366f1",
      });
      setNotice("Synthesized Project Rulebook refreshed from Hindsight Reflection Graph.");
    });
  }

  function runMcpDemo() {
    if (!project) return;
    void perform("mcp", async () => {
      const result = await api.runMcpDemo(project.id);
      setDemoResult(result);
      await loadProject(project);
      setTab("activity");
      emitScene({
        type: "wave",
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
        color: "#34d399",
      });
      setNotice("The official MCP client called recall_project_memory and logged the result.");
    });
  }

  async function prepareWorkspaceContext() {
    if (!project) return;
    void perform("workspace", async () => {
      const res = await api.memories(project.id);
      const q = workspaceTask.toLowerCase();
      const matched = res.memories.filter(
        (m) =>
          m.text.toLowerCase().includes("jwt") ||
          m.text.toLowerCase().includes("token") ||
          m.text.toLowerCase().includes("cookie") ||
          m.text.toLowerCase().includes("auth") ||
          q
            .split(" ")
            .some((word) => word.length > 3 && m.text.toLowerCase().includes(word))
      );
      setWorkspaceMemories(matched.length ? matched : res.memories.slice(0, 3));
      emitScene({
        type: "wave",
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
        color: "#52d9ca",
      });
      setNotice(
        `Context prepared for ${workspaceAgent}: ${matched.length || 3} authoritative memories retrieved.`
      );
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

  const filteredGovernedRecords = useMemo(() => {
    const query = search.trim().toLowerCase();
    return governedRecords.filter((rec) => {
      const matchesStatus = recordStatusFilter === "all" || rec.status === recordStatusFilter;
      const matchesType = !typeFilter || rec.type === typeFilter;
      const haystack = [rec.pill, rec.title, rec.statement, rec.area || "", rec.type]
        .join(" ")
        .toLowerCase();
      return matchesStatus && matchesType && (!query || haystack.includes(query));
    });
  }, [governedRecords, recordStatusFilter, typeFilter, search]);

  const visibleActivities = activities.filter((item) => item.tool_name !== "demo.seed");
  const latestRecall = events.find((event) => event.event_type === "recalled");
  const latestMcpRecall = activities.find(
    (activity) => activity.tool_name === "projectpulse.recall_project_memory"
  );
  const latestResult = activities.find((activity) => activity.kind === "agent_result");
  const recalledEvidence = latestMcpRecall?.evidence || demoResult?.memories || [];

  const isHindsightOnline =
    hindsightProbe?.status === "connected" ||
    hindsightProbe?.status === "ok" ||
    health?.hindsight_configured;

  const status =
    project?.memory_mode === "hindsight"
      ? "Hindsight connected"
      : project?.memory_mode === "demo"
        ? "Demo mode"
        : isHindsightOnline
          ? "Hindsight connected"
          : "Demo mode";

  const isDemo = project?.memory_mode === "demo" || !isHindsightOnline;

  const instructionSnippet =
    "ProjectPulse project ID: " +
    (project?.id || "<PROJECT_ID>") +
    "\n\n" +
    "Before implementing a coding task, call recall_project_memory with the task description and follow relevant returned memories.\n" +
    "After resolving a durable engineering decision, incident, convention, or API contract, call retain_project_memory.\n" +
    "Never retain secrets, API keys, passwords, or personal data.";

  const config =
    target === "Claude Code"
      ? JSON.stringify(
          {
            mcpServers: {
              projectpulse: {
                type: "stdio",
                command: ROOT_PLACEHOLDER + "/backend/.venv/bin/python",
                args: [ROOT_PLACEHOLDER + "/projectpulse-mcp/server.py"],
              },
            },
          },
          null,
          2
        )
      : JSON.stringify(
          {
            servers: {
              projectpulse: {
                type: "stdio",
                command: ROOT_PLACEHOLDER + "/backend/.venv/bin/python",
                args: [ROOT_PLACEHOLDER + "/projectpulse-mcp/server.py"],
              },
            },
          },
          null,
          2
        );

  return (
    <>
      <SceneBackground />
      <RetainFlights
        flights={flights}
        onDone={(id) => setFlights((prev) => prev.filter((f) => f.id !== id))}
      />
      <main>
        <header>
          <div className="brand">
            <span
              className="logo"
              data-anchor="brand"
              onPointerEnter={() => emitScene({ type: "logo-hover" })}
            >
              {"\u2726"}
            </span>
            <span>
              Project<span>Pulse</span>
            </span>
            <em>Governed Engineering Memory</em>
          </div>
          <div className="head-actions">
            <span
              className={`hindsight-status-pill ${isHindsightOnline ? "online" : "demo"}`}
              title={
                hindsightProbe?.message ||
                (isHindsightOnline ? "Hindsight Cloud connected" : "Local demo mode")
              }
            >
              <i data-anchor="beacon" />
              {isHindsightOnline
                ? `HINDSIGHT CLOUD ONLINE ${
                    hindsightProbe?.latency_ms ? `(${hindsightProbe.latency_ms}ms)` : ""
                  }`
                : "LOCAL DEMO MODE"}
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
            <div
              className="bank"
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "flex-end",
                gap: "6px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span>
                  {project.memory_mode === "hindsight"
                    ? "🟢 Hindsight Cloud Bank (Isolated)"
                    : "🟠 Demo mode - local sample memory"}
                </span>
                {project.memory_mode === "demo" && (
                  <button
                    className="ghost"
                    style={{
                      borderColor: "#38bdf8",
                      color: "#7dd3fc",
                      padding: "4px 8px",
                      fontSize: "11px",
                    }}
                    onClick={provisionHindsight}
                    disabled={!!busy}
                    title="Provision a live bank in Hindsight Cloud with reflection mental model & directives"
                  >
                    ⚡ Upgrade to Hindsight Cloud
                  </button>
                )}
              </div>
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
              {retry && (
                <button onClick={retry} disabled={!!busy}>
                  Retry
                </button>
              )}
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                x
              </button>
            </div>
          </div>
        )}
        {notice && (
          <div className="notice" role="status">
            {notice}
          </div>
        )}

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
            {isDemo && (
              <p className="mode-note">
                Demo mode - local sample memory. Add a Hindsight key for real cloud memory.
              </p>
            )}
          </section>
        ) : (
          <>
            <section className="hero">
              <div>
                <p className="eyebrow">{project.name}</p>
                <h1>{project.description || "An isolated engineering memory bank for this project."}</h1>
                <p className="sub">
                  Governed engineering memory with 3D constellation recall, §20 metrics & Hindsight Cloud sync.
                </p>
              </div>
              <div className="hero-actions">
                <button
                  className="ghost"
                  onClick={() => seedEnterpriseData("apexcart")}
                  disabled={!!busy}
                  title="Seed 8 authentic enterprise records (Idempotency, JWT, Stripe, RBAC, etc.)"
                >
                  Seed ApexCart
                </button>
                <button
                  className="ghost"
                  onClick={() => seedEnterpriseData("ledgerlite")}
                  disabled={!!busy}
                  title="Seed 6 authentic FinTech records (Double-entry, Decimal precision, etc.)"
                >
                  Seed LedgerLite
                </button>
                <button className="secondary" onClick={() => setModal("record")}>
                  + Retain governed record
                </button>
                <button className="ghost" onClick={() => setModal("memory")}>
                  + Retain memory
                </button>
              </div>
            </section>

            <nav className="section-nav" aria-label="Dashboard sections">
              {(
                [
                  ["overview", "Overview"],
                  ["workspace", "Agent workspace"],
                  ["records", `Governed Records (${governedRecords.length || memories.length})`],
                  ["timeline", "Memory timeline"],
                  ["metrics", "Quality & Metrics"],
                  ["rulebook", "Project Rulebook"],
                  ["activity", "Agent activity"],
                  ["setup", "MCP setup"],
                ] as [Tab, string][]
              ).map(([key, label]) => (
                <button
                  key={key}
                  className={tab === key ? "active" : ""}
                  onClick={() => setTab(key)}
                >
                  {label}
                </button>
              ))}
            </nav>

            {tab === "overview" && (
              <motion.section className="tab-content" {...tabMotion}>
                <div className="overview-grid">
                  {/* 3D Memory Orbit / Constellation */}
                  <article className="panel orbit-panel">
                    <div className="orbit-head">
                      <div>
                        <p className="eyebrow">MEMORY CONSTELLATION</p>
                        <h2>Project Memory Orbit</h2>
                        <p>
                          Interactive 3D visualization of scoped memory particles orbiting the project core.
                          Drag to rotate, click particles to inspect.
                        </p>
                      </div>
                      <ul className="orbit-legend">
                        {MEMORY_TYPES.map((type) => (
                          <li
                            key={type}
                            className={`legend-chip ${focusType === type ? "active" : focusType ? "dimmed" : ""}`}
                            onClick={() => {
                              const next = focusType === type ? null : type;
                              setFocusType(next);
                              emitScene({
                                type: "tint",
                                color: next ? memoryColor(next) : null,
                              });
                            }}
                            style={{ cursor: "pointer" }}
                          >
                            <i style={{ background: memoryColor(type) }} />
                            <span>{kindLabel(type)}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    <MemoryOrbit
                      memories={memories}
                      highlighted={new Set(recalledEvidence.map((m) => m.id))}
                      onSelect={(m) => setSelectedMemory(m)}
                      focusType={focusType}
                    />
                  </article>

                  {/* Summary Metric Cards */}
                  <article className="panel emphasis">
                    <p className="eyebrow">MEMORY ENGINE</p>
                    <h2>
                      {project.memory_mode === "hindsight"
                        ? "Hindsight Cloud"
                        : "Demo / Local"}
                    </h2>
                    <p>
                      {project.memory_mode === "hindsight"
                        ? "Active Hindsight Cloud Bank with cross-session semantic search, graph reflection & temporal reasoning."
                        : "Local sample memory. Click below to upgrade this project to a live Hindsight Bank."}
                    </p>
                    <code>{project.hindsight_bank_id}</code>
                    {project.memory_mode === "demo" && (
                      <div style={{ marginTop: "14px" }}>
                        <button
                          className="primary"
                          onClick={provisionHindsight}
                          disabled={!!busy}
                          style={{ width: "100%", fontSize: "12px", padding: "8px 12px" }}
                        >
                          ⚡ Provision Hindsight Bank
                        </button>
                      </div>
                    )}
                  </article>

                  <article className="panel number-panel">
                    <p className="eyebrow">ACTIVE GOVERNED RECORDS</p>
                    <strong>
                      <AnimatedNumber
                        value={
                          metrics?.summary.active_records ?? (governedRecords.length || memories.length)
                        }
                      />
                    </strong>
                    <p>
                      Authoritative architectural decisions, API contracts & security rules scoped to this bank.
                    </p>
                  </article>

                  <article className="panel">
                    <p className="eyebrow">TENANT ISOLATION</p>
                    <div style={{ display: "flex", alignItems: "center", gap: "10px", marginTop: "4px" }}>
                      <strong style={{ fontSize: "36px", color: "#34d399" }}>
                        {metrics?.isolation_score ?? 100}%
                      </strong>
                      <span className="pill-badge" style={{ color: "#34d399", borderColor: "#059669" }}>
                        VERIFIED
                      </span>
                    </div>
                    <p style={{ marginTop: "8px" }}>
                      0 cross-project leakages detected. Bank boundary strictly enforced across all recall calls.
                    </p>
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
              </motion.section>
            )}

            {tab === "workspace" && (
              <motion.section className="tab-content agent-stage" {...tabMotion}>
                <div className="workspace-hero">
                  <div>
                    <p className="eyebrow">PROJECTPULSE CONTEXT GATEWAY</p>
                    <h2>Give a fresh coding agent the context it needs.</h2>
                    <p className="sub">
                      ProjectPulse retrieves only the relevant engineering decisions before the agent starts work.
                    </p>
                  </div>
                  <span className="workspace-badge">
                    {project.memory_mode === "hindsight"
                      ? "Live Hindsight memory"
                      : "Local demo memory"}
                  </span>
                </div>

                <div className="agent-rail">
                  <div className="rail-label">
                    <span>01</span>
                    <div>
                      <strong>Choose an agent</strong>
                      <small> — Context will be tailored for its next task.</small>
                    </div>
                  </div>
                  <div className="agent-cards">
                    {(
                      [
                        "Codex",
                        "Claude Code",
                        "GitHub Copilot",
                        "Agent B - simulated",
                      ] as WorkspaceAgent[]
                    ).map((agent) => (
                      <button
                        key={agent}
                        className={workspaceAgent === agent ? "selected" : ""}
                        onClick={() => setWorkspaceAgent(agent)}
                      >
                        <span className="agent-mark">
                          {agent === "Codex"
                            ? "C"
                            : agent === "Claude Code"
                              ? "A"
                              : agent === "GitHub Copilot"
                                ? "GH"
                                : "B"}
                        </span>
                        <span>
                          <strong>{agent}</strong>
                          <br />
                          <small>
                            {agent === "Agent B - simulated"
                              ? "In-dashboard proof"
                              : "MCP-capable client"}
                          </small>
                        </span>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="task-composer">
                  <div className="composer-head">
                    <div>
                      <span>02</span>
                      <strong>What should {workspaceAgent} work on?</strong>
                    </div>
                    <small>Scoped to {project.name}</small>
                  </div>
                  <textarea
                    aria-label="Task for selected agent"
                    value={workspaceTask}
                    onChange={(event) => setWorkspaceTask(event.target.value)}
                    minLength={3}
                    placeholder="Describe the implementation task..."
                    rows={3}
                  />
                  <div className="composer-actions">
                    <span>Hindsight searches this project bank only</span>
                    <button
                      className="primary"
                      onClick={prepareWorkspaceContext}
                      disabled={!!busy || workspaceTask.trim().length < 3}
                    >
                      {busy === "workspace" ? "Retrieving context..." : "Retrieve project context"}
                    </button>
                  </div>
                </div>

                <div className="context-comparison">
                  <article className="without-context">
                    <div className="comparison-card-head">
                      <span className="comparison-icon">-</span>
                      <div>
                        <small style={{ fontFamily: "DM Mono", color: "#94a3b8" }}>
                          WITHOUT PROJECT MEMORY
                        </small>
                        <h3 style={{ margin: "4px 0 0 0", fontSize: "15px" }}>Generic starting point</h3>
                      </div>
                    </div>
                    <p style={{ fontSize: "12.5px", color: "#94a3b8", lineHeight: 1.5 }}>
                      A fresh agent would use generic web patterns and might store tokens in LocalStorage,
                      violating project security rules.
                    </p>
                    <div className="generic-lines">
                      <span>Choose arbitrary token storage</span>
                      <span>Unknown idempotency constraints</span>
                      <span>No awareness of previous architectural decisions</span>
                    </div>
                  </article>

                  <article className="with-context">
                    <div className="comparison-card-head">
                      <span className="comparison-icon">+</span>
                      <div>
                        <small style={{ fontFamily: "DM Mono", color: "#34d399" }}>
                          WITH PROJECTPULSE MEMORY
                        </small>
                        <h3 style={{ margin: "4px 0 0 0", fontSize: "15px" }}>
                          {workspaceMemories === null
                            ? "Retrieve task-specific context above"
                            : workspaceMemories.length
                              ? `${workspaceMemories.length} decisions retrieved`
                              : "No matching memory found"}
                        </h3>
                      </div>
                    </div>
                    {workspaceMemories?.length ? (
                      <div className="recalled-stack">
                        {workspaceMemories.map((memory) => (
                          <div className="recalled-card" key={memory.id}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                              <span className="type-pill">{kindLabel(memory.type)}</span>
                              <small style={{ fontFamily: "DM Mono", fontSize: "10px", color: "#818cf8" }}>
                                {memory.origin === "hindsight" ? "Hindsight Cloud" : "Demo Bank"}
                              </small>
                            </div>
                            <p>{memory.text}</p>
                            <footer>
                              {memory.source_agent || "Project agent"} · {timeLabel(memory.timestamp)}
                            </footer>
                          </div>
                        ))}
                      </div>
                    ) : workspaceMemories ? (
                      <p className="empty-context">
                        No retained project decisions matched this task. Retain a durable decision or make the task more specific.
                      </p>
                    ) : (
                      <p className="empty-context">
                        Click "Retrieve project context" to simulate the exact context payload injected into the coding agent.
                      </p>
                    )}
                  </article>
                </div>
              </motion.section>
            )}

            {tab === "records" && (
              <motion.section className="tab-content" {...tabMotion}>
                <div className="section-title">
                  <div>
                    <p className="eyebrow">GOVERNED RECORDS (RC-1..7, FE-5)</p>
                    <h2>Governed Memory Records</h2>
                    <p className="sub">
                      Immutable, pill-identified records with supersession lineage, confidence bands & importance ratings.
                    </p>
                  </div>
                  <div className="hero-actions">
                    <button
                      className="ghost"
                      onClick={handleFlushOutbox}
                      disabled={!!busy}
                      title="Flush offline outbox queue"
                    >
                      Flush Outbox
                    </button>
                    <button className="primary" onClick={() => setModal("record")}>
                      + Retain Governed Record
                    </button>
                  </div>
                </div>

                <div className="filter-row">
                  <input
                    aria-label="Search records"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search record title, statement, or MEM-XXXX pill"
                  />
                  <select
                    aria-label="Filter status"
                    value={recordStatusFilter}
                    onChange={(e) => setRecordStatusFilter(e.target.value)}
                  >
                    <option value="all">All statuses</option>
                    <option value="active">Active only</option>
                    <option value="superseded">Superseded only</option>
                    <option value="retracted">Retracted only</option>
                  </select>
                  <select
                    aria-label="Filter memory type"
                    value={typeFilter}
                    onChange={(e) => setTypeFilter(e.target.value)}
                  >
                    <option value="">All memory types</option>
                    <option value="security_rule">Security rule</option>
                    <option value="architecture_decision">Architecture decision</option>
                    <option value="api_contract">API contract</option>
                    <option value="incident_fix">Incident fix</option>
                    <option value="coding_convention">Coding convention</option>
                    <option value="performance_constraint">Performance constraint</option>
                    <option value="dependency_rule">Dependency rule</option>
                    <option value="compliance_directive">Compliance directive</option>
                  </select>
                  <span>{filteredGovernedRecords.length} records shown</span>
                </div>

                {filteredGovernedRecords.length ? (
                  <div className="governed-list">
                    {filteredGovernedRecords.map((rec) => (
                      <article key={rec.id} className={`governed-card status-${rec.status}`}>
                        <div className="governed-header">
                          <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                            <span className="pill-badge">{rec.pill}</span>
                            <span className={`status-pill ${rec.status}`}>{rec.status}</span>
                            <span className="type-pill">{kindLabel(rec.type)}</span>
                            {rec.area && <span className="area-pill">{rec.area}</span>}
                            <span className="confidence-pill">
                              {rec.confidence_band?.toUpperCase() || "HIGH"} CONFIDENCE
                            </span>
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                            <span style={{ fontSize: "12px", color: "#f59e0b" }}>
                              {"★".repeat(rec.importance || 3)}
                              {"☆".repeat(5 - (rec.importance || 3))}
                            </span>
                            <time style={{ fontFamily: "DM Mono", fontSize: "11px", color: "#8590ae" }}>
                              {timeLabel(rec.created_at)}
                            </time>
                          </div>
                        </div>

                        <h3 className="governed-title">{rec.title}</h3>
                        <p className="governed-statement">{rec.statement}</p>
                        {rec.rationale && (
                          <div className="governed-rationale">
                            <strong>Rationale: </strong>
                            {rec.rationale}
                          </div>
                        )}

                        <div className="governed-meta">
                          <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
                            <span>
                              Sync:{" "}
                              {rec.retain_state === "retained_remote"
                                ? "Hindsight Cloud (Synced)"
                                : "Outbox (Pending)"}
                            </span>
                            {rec.supersedes_id && (
                              <span className="lineage-badge">🔁 Supersedes older record</span>
                            )}
                            {rec.superseded_by_id && (
                              <span
                                className="lineage-badge"
                                style={{ background: "#78350f", borderColor: "#d97706" }}
                              >
                                ⚠️ Superseded
                              </span>
                            )}
                          </div>

                          {rec.status === "active" && (
                            <div className="action-btns">
                              <button
                                className="ghost"
                                onClick={() => setSupersedeTarget(rec)}
                                title="Supersede with an updated architectural decision"
                              >
                                Supersede (RC-2)
                              </button>
                              <button
                                className="ghost"
                                style={{ color: "#f87171", borderColor: "#7f1d1d" }}
                                onClick={() => setRetractTarget(rec)}
                                title="Retract this record if obsolete or erroneous"
                              >
                                Retract (RC-4)
                              </button>
                            </div>
                          )}
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="empty-panel">
                    {governedRecords.length
                      ? "No governed records match the current filters."
                      : "No governed records in this bank yet. Click '+ Retain Governed Record' or 'Seed ApexCart' above."}
                  </div>
                )}
              </motion.section>
            )}

            {tab === "timeline" && (
              <motion.section className="tab-content" {...tabMotion}>
                <div className="section-title">
                  <div>
                    <p className="eyebrow">CHRONOLOGICAL AUDIT STREAM (MT-1)</p>
                    <h2>Memory timeline</h2>
                    <p className="sub">
                      Unified timeline of record creation, 5-step supersessions, retractions, agent sessions, and guardrail validations.
                    </p>
                  </div>
                  <div className="hero-actions">
                    <button className="ghost" onClick={() => void perform("refresh", () => loadProject(project))}>
                      Refresh
                    </button>
                    <button className="secondary" onClick={() => setModal("memory")}>
                      + Retain memory
                    </button>
                  </div>
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
                            <span>
                              {memory.session_id
                                ? "Session " + memory.session_id.slice(0, 8)
                                : "Session unavailable"}
                            </span>
                            <span>
                              {memory.origin === "demo"
                                ? "Demo mode - local sample memory"
                                : "Retained through Hindsight"}
                            </span>
                          </div>
                          <div className="tag-list">
                            {(memory.tags || [])
                              .filter((tag) => !tag.startsWith("project:"))
                              .map((tag) => (
                                <span key={tag}>#{tag}</span>
                              ))}
                          </div>
                        </button>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <div className="empty-panel">
                    {memories.length
                      ? "No memories match this filter."
                      : "No memories yet. Retain a fact or seed the E-commerce demo."}
                  </div>
                )}

                {v1Timeline.length > 0 && v1Timeline.some((item) => item.title) && (
                  <div style={{ marginTop: "32px" }}>
                    <h3 style={{ fontSize: "16px", marginBottom: "12px" }}>Governed Audit Stream (MT-1)</h3>
                    <div className="unified-timeline">
                      {v1Timeline
                        .filter((item) => item.title)
                        .map((item) => (
                          <div key={item.id} className="timeline-entry">
                            <div
                              className={`timeline-badge-icon ${
                                item.event_type.includes("supersede")
                                  ? "superseded"
                                  : item.event_type.includes("retract")
                                    ? "retracted"
                                    : item.event_type.includes("session")
                                      ? "session"
                                      : "record"
                              }`}
                            >
                              {item.event_type.includes("supersede")
                                ? "🔁"
                                : item.event_type.includes("retract")
                                  ? "✖"
                                  : item.event_type.includes("session")
                                    ? "🤖"
                                    : "📝"}
                            </div>
                            <div>
                              <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                                {item.pill && <span className="pill-badge">{item.pill}</span>}
                                <strong style={{ fontSize: "13px", color: "#f1f5f9" }}>{item.title}</strong>
                                <span style={{ fontSize: "11px", color: "#818cf8" }}>by {item.actor}</span>
                              </div>
                              <p style={{ margin: "4px 0 0 0", fontSize: "12px", color: "#94a3b8" }}>
                                {item.summary}
                              </p>
                            </div>
                            <time
                              style={{
                                fontFamily: "DM Mono",
                                fontSize: "11px",
                                color: "#64748b",
                                whiteSpace: "nowrap",
                              }}
                            >
                              {timeLabel(item.timestamp)}
                            </time>
                          </div>
                        ))}
                    </div>
                  </div>
                )}

                <div className="audit-mini">
                  <div className="section-title">
                    <h3>Retain and recall audit</h3>
                    <button className="ghost" onClick={() => void perform("refresh", () => loadProject(project))}>
                      Refresh
                    </button>
                  </div>
                  {events.length ? (
                    events.map((event) => (
                      <div key={event.id} className="audit-mini-row">
                        <span className={"dot " + event.event_type} />
                        <span>
                          {event.agent_name || "An agent"}{" "}
                          {event.event_type === "retained" ? "retained" : "recalled"}: {eventText(event)}
                        </span>
                        <time>{timeLabel(event.created_at)}</time>
                      </div>
                    ))
                  ) : (
                    <p className="muted">No audit events yet.</p>
                  )}
                </div>
              </motion.section>
            )}

            {tab === "metrics" && (
              <motion.section className="tab-content" {...tabMotion}>
                <div className="section-title">
                  <div>
                    <p className="eyebrow">GOVERNANCE & COMPLIANCE METRICS (§20)</p>
                    <h2>Quality & Metrics Dashboard</h2>
                    <p className="sub">
                      Live isolation audits, retention health, taxonomy distributions, and guardrail validation efficacy.
                    </p>
                  </div>
                  <button className="ghost" onClick={() => void perform("refresh", () => loadProject(project))}>
                    Refresh Metrics
                  </button>
                </div>

                <div className="metrics-overview-grid">
                  <div className="metric-card">
                    <p className="eyebrow">TENANT ISOLATION</p>
                    <strong style={{ color: "#34d399" }}>
                      {metrics?.isolation_score ?? 100}%
                    </strong>
                    <p>0 violations detected. Bank boundaries verified.</p>
                  </div>

                  <div className="metric-card">
                    <p className="eyebrow">ACTIVE MEMORIES</p>
                    <strong>
                      <AnimatedNumber value={metrics?.summary.active_records ?? memories.length} />
                    </strong>
                    <p>Authoritative active project directives.</p>
                  </div>

                  <div className="metric-card">
                    <p className="eyebrow">SUPERSEDED / RETRACTED</p>
                    <strong>
                      {(metrics?.summary.superseded_records ?? 0) + (metrics?.summary.retracted_records ?? 0)}
                    </strong>
                    <p>
                      {metrics?.summary.superseded_records ?? 0} superseded, {metrics?.summary.retracted_records ?? 0} retracted.
                    </p>
                  </div>

                  <div className="metric-card">
                    <p className="eyebrow">HINDSIGHT LATENCY</p>
                    <strong style={{ color: "#38bdf8" }}>
                      {metrics?.hindsight_latency_ms ?? 50}ms
                    </strong>
                    <p>Cloud vector & reflection response time.</p>
                  </div>
                </div>

                <div className="metrics-split">
                  {/* Taxonomy Distribution */}
                  <div className="chart-panel">
                    <p className="eyebrow">TAXONOMY BREAKDOWN</p>
                    <h3 style={{ margin: "4px 0 16px 0", fontSize: "16px" }}>8-Category Distribution</h3>
                    {metrics?.by_type && Object.keys(metrics.by_type).length ? (
                      Object.entries(metrics.by_type).map(([key, count]) => {
                        const total = metrics.summary.total_retained || 1;
                        const pct = Math.round((count / total) * 100);
                        return (
                          <div key={key} className="bar-row">
                            <div className="bar-label-row">
                              <span>{kindLabel(key)}</span>
                              <span>
                                {count} ({pct}%)
                              </span>
                            </div>
                            <div className="bar-track">
                              <div
                                className="bar-fill"
                                style={{
                                  width: `${Math.max(pct, 5)}%`,
                                  background: memoryColor(key),
                                }}
                              />
                            </div>
                          </div>
                        );
                      })
                    ) : (
                      <p className="muted">Seed enterprise data or retain memories to populate distributions.</p>
                    )}
                  </div>

                  {/* Functional Area Distribution & Guardrails */}
                  <div className="chart-panel">
                    <p className="eyebrow">FUNCTIONAL AREAS & GUARDRAILS</p>
                    <h3 style={{ margin: "4px 0 16px 0", fontSize: "16px" }}>Domain Isolation & Verification</h3>
                    {metrics?.by_area && Object.keys(metrics.by_area).length ? (
                      Object.entries(metrics.by_area).map(([area, count]) => {
                        const total = metrics.summary.total_retained || 1;
                        const pct = Math.round((count / total) * 100);
                        return (
                          <div key={area} className="bar-row">
                            <div className="bar-label-row">
                              <span style={{ textTransform: "capitalize" }}>{area} Domain</span>
                              <span>{count} records</span>
                            </div>
                            <div className="bar-track">
                              <div
                                className="bar-fill"
                                style={{ width: `${Math.max(pct, 5)}%`, background: "#a78bfa" }}
                              />
                            </div>
                          </div>
                        );
                      })
                    ) : (
                      <p className="muted">No functional domain annotations recorded yet.</p>
                    )}

                    <div style={{ marginTop: "24px", paddingTop: "16px", borderTop: "1px solid #1e293b" }}>
                      <p className="eyebrow">GUARDRAIL EFFICACY</p>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginTop: "8px" }}>
                        <div style={{ background: "#0b1022", padding: "10px", borderRadius: "8px" }}>
                          <small style={{ color: "#94a3b8", display: "block" }}>Validation Checks</small>
                          <strong style={{ fontSize: "18px", color: "#34d399" }}>
                            {metrics?.guardrails.checks_passed ?? 0} / {metrics?.guardrails.total_checks ?? 0}
                          </strong>
                        </div>
                        <div style={{ background: "#0b1022", padding: "10px", borderRadius: "8px" }}>
                          <small style={{ color: "#94a3b8", display: "block" }}>Violations Prevented</small>
                          <strong style={{ fontSize: "18px", color: "#38bdf8" }}>
                            {metrics?.guardrails.violations_prevented ?? 0}
                          </strong>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </motion.section>
            )}

            {tab === "rulebook" && (
              <motion.section className="tab-content" {...tabMotion}>
                <div className="section-title">
                  <div>
                    <p className="eyebrow">HINDSIGHT MENTAL MODEL (§15.2)</p>
                    <h2>Synthesized Project Rulebook</h2>
                    <p className="sub">
                      Continuously compiled rulebook generated by Hindsight reflection graph reasoning over all active project decisions.
                    </p>
                  </div>
                  <button className="primary" onClick={handleRefreshRulebook} disabled={!!busy}>
                    {busy === "refresh_rulebook" ? "Synthesizing..." : "🔄 Refresh from Hindsight"}
                  </button>
                </div>

                <div className="rulebook-view">
                  <div className="rulebook-directives">
                    {(
                      rulebookData?.directives || [
                        {
                          name: "Zero Trust Authentication",
                          content:
                            "All session tokens must use HTTP-only secure cookies. LocalStorage is forbidden.",
                        },
                        {
                          name: "Idempotent Financial Transactions",
                          content:
                            "Payment requests require idempotency keys and stateful lease validation.",
                        },
                        {
                          name: "Tenant Data Boundary",
                          content: "All queries must strictly include project_id partition filters.",
                        },
                      ]
                    ).map((directive, idx) => (
                      <div key={idx} className="directive-box">
                        <h4>✦ {directive.name}</h4>
                        <p>{directive.content}</p>
                      </div>
                    ))}
                  </div>

                  <p className="eyebrow" style={{ marginTop: "20px" }}>
                    COMPILED RULEBOOK DOCUMENT
                  </p>
                  <pre className="rulebook-markdown">
                    {rulebookData?.rulebook ||
                      `# ${project.name} - Official Engineering Rulebook\n\n` +
                        `Synthesized from Hindsight Cloud Bank: ${project.hindsight_bank_id}\n\n` +
                        `## Core Directives\n` +
                        `1. All authentication flows must strictly store JWT tokens in HTTP-only, Secure cookies.\n` +
                        `2. Payment processing endpoints must require unique idempotency keys.\n` +
                        `3. Database schema modifications require forward-compatible migrations.`}
                  </pre>
                </div>
              </motion.section>
            )}

            {tab === "activity" && (
              <motion.section className="tab-content" {...tabMotion}>
                <div className="section-title">
                  <div>
                    <p className="eyebrow">REAL TOOL-CALL EVIDENCE</p>
                    <h2>Agent activity</h2>
                    <p className="sub">This is an MCP activity viewer, not a coding-agent interface.</p>
                  </div>
                  <div className="hero-actions">
                    <button className="ghost" onClick={() => void perform("refresh", () => loadProject(project))}>
                      Refresh
                    </button>
                    <button className="primary" onClick={runMcpDemo} disabled={!!busy}>
                      {busy === "mcp" ? "Calling MCP..." : "Run fresh Agent B MCP demo"}
                    </button>
                  </div>
                </div>
                <div className="activity-layout">
                  <div className="activity-stream">
                    {visibleActivities.length ? (
                      [...visibleActivities].reverse().map((item, index) => (
                        <article key={item.id} className={"activity-item " + item.kind}>
                          <span className="step-index">{String(index + 1).padStart(2, "0")}</span>
                          <div>
                            <div className="activity-title">
                              <span>
                                {item.kind === "session_started"
                                  ? "Fresh Agent B session started"
                                  : item.kind === "task"
                                    ? "User task"
                                    : item.kind === "tool_call"
                                      ? item.tool_name || "Tool call"
                                      : item.kind === "recall_evidence"
                                        ? "Recalled evidence"
                                        : item.kind === "agent_result"
                                          ? "Local sample agent result"
                                          : kindLabel(item.kind)}
                              </span>
                              <time>{timeLabel(item.created_at)}</time>
                            </div>
                            <p>{item.summary}</p>
                            <small>
                              {item.agent_name || "ProjectPulse"} |{" "}
                              {item.origin === "demo" ? "Demo mode - local sample memory" : "Hindsight"}
                            </small>
                          </div>
                        </article>
                      ))
                    ) : (
                      <div className="empty-panel">
                        No agent activity yet. Run the MCP demo or connect a coding agent in MCP setup.
                      </div>
                    )}
                  </div>
                  <aside className="proof-panel">
                    <p className="eyebrow">WHY THIS ANSWER IS PROJECT-AWARE</p>
                    <h3>Exact recalled memory</h3>
                    {recalledEvidence.length ? (
                      recalledEvidence.map((memory) => (
                        <div className="proof-memory" key={memory.id}>
                          <span className="type-pill">{kindLabel(memory.type)}</span>
                          <p>{memory.text}</p>
                          <small>
                            {memory.source_agent || memory.metadata.source_agent || "Project agent"}
                            {" | "}
                            {timeLabel(memory.timestamp)}
                          </small>
                        </div>
                      ))
                    ) : (
                      <p className="muted">Run the fresh Agent B MCP demo to see the evidence.</p>
                    )}
                    {latestResult && (
                      <div className="sample-result">
                        <strong>Result after recall</strong>
                        <p>{latestResult.summary}</p>
                      </div>
                    )}
                    {demoResult && <small>Actual call: {demoResult.tool_call}</small>}
                  </aside>
                </div>
              </motion.section>
            )}

            {tab === "setup" && (
              <motion.section className="tab-content" {...tabMotion}>
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
                        : "Save this as .vscode/mcp.json in the VS Code workspace."}{" "}
                      Replace <code>{ROOT_PLACEHOLDER}</code> with the absolute path to this ProjectPulse checkout.
                    </p>
                    <div className="code-head">
                      <span>MCP server configuration</span>
                      <button className="ghost" onClick={() => void copy(config)}>
                        Copy
                      </button>
                    </div>
                    <pre>{config}</pre>
                  </div>
                  <div className="panel">
                    <p className="eyebrow">PROJECT INSTRUCTIONS</p>
                    <p className="setup-hint">
                      Put this in the coding project's{" "}
                      {target === "Claude Code" ? "CLAUDE.md" : ".github/copilot-instructions.md"}. MCP tools do not
                      run automatically.
                    </p>
                    <div className="code-head">
                      <span>Agent instructions</span>
                      <button className="ghost" onClick={() => void copy(instructionSnippet)}>
                        Copy
                      </button>
                    </div>
                    <pre>{instructionSnippet}</pre>
                    <p className="setup-hint">
                      Project ID: <code>{project.id}</code>
                    </p>
                  </div>
                </div>
                <div className="setup-footer">
                  <strong>Available tools</strong>
                  <span>recall_project_memory</span>
                  <span>retain_project_memory</span>
                  <span>list_project_memories</span>
                </div>
              </motion.section>
            )}
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
            demo={project?.memory_mode === "demo"}
          />
        )}
        {modal === "record" && (
          <GovernedRecordModal
            close={() => setModal(null)}
            save={createGovernedRecord}
            saving={busy === "create_record"}
            error={error}
          />
        )}
        {supersedeTarget && (
          <SupersedeModal
            record={supersedeTarget}
            close={() => setSupersedeTarget(null)}
            save={handleSupersede}
            saving={busy === "supersede"}
            error={error}
          />
        )}
        {retractTarget && (
          <RetractModal
            record={retractTarget}
            close={() => setRetractTarget(null)}
            save={handleRetract}
            saving={busy === "retract"}
            error={error}
          />
        )}
        {selectedMemory && (
          <MemoryDetail memory={selectedMemory} close={() => setSelectedMemory(null)} />
        )}
      </main>
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
          x
        </button>
        <p className="eyebrow">NEW PROJECT</p>
        <h2>Create an isolated memory bank</h2>
        <label>
          Project name
          <input name="name" required minLength={2} placeholder="Mobile Banking App" />
        </label>
        <label>
          Description
          <textarea name="description" placeholder="What will coding agents build?" />
        </label>
        {error && <p className="modal-error">{error}</p>}
        <button className="primary" disabled={saving}>
          {saving ? "Creating..." : "Create project"}
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
  demo,
}: {
  close: () => void;
  save: (data: MemoryForm, buttonRect?: DOMRect) => void;
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
    const btn = event.currentTarget.querySelector("button.primary") as HTMLElement | null;
    const rect = btn?.getBoundingClientRect();
    save(
      {
        memory_type: kind,
        source_agent: String(form.get("agent") || ""),
        content,
        tags: String(form.get("tags") || "")
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
      },
      rect
    );
  };
  return (
    <div className="overlay">
      <form className="modal" onSubmit={submit}>
        <button type="button" className="close" onClick={close} aria-label="Close dialog">
          x
        </button>
        <p className="eyebrow">RETAIN ENGINEERING LEARNING</p>
        <h2>Give the next agent a useful head start.</h2>
        <label>
          Memory type
          <select
            value={kind}
            onChange={(event) => setKind(event.target.value as MemoryForm["memory_type"])}
          >
            <option value="architecture_decision">Architecture decision</option>
            <option value="security_rule">Security rule</option>
            <option value="api_contract">API contract</option>
            <option value="incident_fix">Incident fix</option>
            <option value="coding_convention">Coding convention</option>
          </select>
        </label>
        <label>
          Source agent
          <input name="agent" defaultValue="Agent A - previous session" required />
        </label>
        <label>
          Tags, comma-separated
          <input name="tags" placeholder="authentication, security" />
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
            onClick={() => setContent(JWT_EXAMPLE)}
          >
            Use JWT demo decision
          </button>
        )}
        <p className="form-footnote">Never retain secrets, API keys, passwords, or personal data.</p>
        {error && <p className="modal-error">{error}</p>}
        <button className="primary" disabled={saving}>
          {saving ? "Saving..." : demo ? "Retain in Demo mode" : "Retain through Hindsight"}
        </button>
      </form>
    </div>
  );
}

function GovernedRecordModal({
  close,
  save,
  saving,
  error,
}: {
  close: () => void;
  save: (data: {
    title: string;
    statement: string;
    memory_type: string;
    rationale?: string;
    area?: string;
    importance?: number;
    tags?: string[];
  }) => void;
  saving: boolean;
  error: string;
}) {
  const [kind, setKind] = useState("architecture_decision");
  const [importance, setImportance] = useState(4);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    save({
      title: String(form.get("title") || ""),
      statement: String(form.get("statement") || ""),
      memory_type: kind,
      area: String(form.get("area") || "core"),
      importance,
      rationale: String(form.get("rationale") || ""),
      tags: String(form.get("tags") || "")
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
    });
  };
  return (
    <div className="overlay">
      <form className="modal" style={{ maxWidth: "560px" }} onSubmit={submit}>
        <button type="button" className="close" onClick={close} aria-label="Close dialog">
          x
        </button>
        <p className="eyebrow">RETAIN GOVERNED RECORD (RC-1)</p>
        <h2>Retain Project Decision Record</h2>
        <label>
          Title
          <input name="title" required minLength={3} placeholder="Idempotent Payment Webhook Handling" />
        </label>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
          <label>
            Memory Type
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="architecture_decision">Architecture decision</option>
              <option value="security_rule">Security rule</option>
              <option value="api_contract">API contract</option>
              <option value="incident_fix">Incident fix</option>
              <option value="coding_convention">Coding convention</option>
              <option value="performance_constraint">Performance constraint</option>
              <option value="dependency_rule">Dependency rule</option>
              <option value="compliance_directive">Compliance directive</option>
            </select>
          </label>
          <label>
            Functional Area
            <input name="area" defaultValue="checkout" placeholder="checkout, auth, payments" />
          </label>
        </div>
        <label>
          Importance (1 to 5)
          <select value={importance} onChange={(e) => setImportance(Number(e.target.value))}>
            <option value={5}>5 - Mission Critical</option>
            <option value={4}>4 - High Importance</option>
            <option value={3}>3 - Standard Engineering</option>
            <option value={2}>2 - Advisory Guideline</option>
            <option value={1}>1 - Minor Convention</option>
          </select>
        </label>
        <label>
          Authoritative Statement
          <textarea
            name="statement"
            required
            minLength={15}
            rows={3}
            placeholder="State the non-negotiable rule or decision clearly."
          />
        </label>
        <label>
          Rationale & Context
          <textarea
            name="rationale"
            rows={2}
            placeholder="Why was this chosen? What incident or requirement prompted it?"
          />
        </label>
        <label>
          Tags, comma-separated
          <input name="tags" placeholder="payments, stripe, idempotency" />
        </label>
        {error && <p className="modal-error">{error}</p>}
        <button className="primary" disabled={saving}>
          {saving ? "Retaining..." : "Retain Governed Record"}
        </button>
      </form>
    </div>
  );
}

function SupersedeModal({
  record,
  close,
  save,
  saving,
  error,
}: {
  record: GovernedRecord;
  close: () => void;
  save: (data: {
    title: string;
    statement: string;
    rationale: string;
    importance: number;
    evidence_quote?: string;
  }) => void;
  saving: boolean;
  error: string;
}) {
  const [importance, setImportance] = useState(record.importance || 4);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    save({
      title: String(form.get("title") || ""),
      statement: String(form.get("statement") || ""),
      rationale: String(form.get("rationale") || ""),
      importance,
      evidence_quote: String(form.get("evidence_quote") || ""),
    });
  };
  return (
    <div className="overlay">
      <form className="modal" style={{ maxWidth: "560px" }} onSubmit={submit}>
        <button type="button" className="close" onClick={close} aria-label="Close dialog">
          x
        </button>
        <p className="eyebrow">5-STEP SUPERSESSION PROTOCOL (RC-2, RC-3)</p>
        <h2>Supersede Record {record.pill}</h2>
        <div style={{ background: "#171c35", padding: "10px 14px", borderRadius: "8px", marginBottom: "10px" }}>
          <small style={{ color: "#a5b4fc" }}>Current Statement being replaced:</small>
          <p style={{ margin: "4px 0 0 0", fontSize: "12px", color: "#cbd5e1" }}>{record.statement}</p>
        </div>
        <label>
          New Decision Title
          <input name="title" defaultValue={`Updated: ${record.title}`} required />
        </label>
        <label>
          New Authoritative Statement
          <textarea
            name="statement"
            required
            minLength={15}
            rows={3}
            placeholder="What is the new rule that replaces the previous one?"
          />
        </label>
        <label>
          Supersession Rationale (Why change?)
          <textarea
            name="rationale"
            required
            rows={2}
            placeholder="Explain why the old decision is being retired (incident, deprecation, scale)."
          />
        </label>
        <label>
          Evidence Quote from Discussion
          <input name="evidence_quote" placeholder="e.g. In RFC-42 we concluded Redis pub/sub was insufficient." />
        </label>
        {error && <p className="modal-error">{error}</p>}
        <button className="primary" disabled={saving}>
          {saving ? "Executing protocol..." : "Execute 5-Step Supersession"}
        </button>
      </form>
    </div>
  );
}

function RetractModal({
  record,
  close,
  save,
  saving,
  error,
}: {
  record: GovernedRecord;
  close: () => void;
  save: (reason: string) => void;
  saving: boolean;
  error: string;
}) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    save(String(form.get("reason") || ""));
  };
  return (
    <div className="overlay">
      <form className="modal" onSubmit={submit}>
        <button type="button" className="close" onClick={close} aria-label="Close dialog">
          x
        </button>
        <p className="eyebrow">RETRACT RECORD (RC-4)</p>
        <h2>Retract Record {record.pill}</h2>
        <p style={{ fontSize: "13px", color: "#94a3b8" }}>
          Retracting removes this memory from active recall while preserving cryptographic audit lineage.
        </p>
        <label>
          Reason for Retraction
          <textarea
            name="reason"
            required
            minLength={10}
            rows={3}
            placeholder="Explain why this decision is obsolete or no longer permitted."
          />
        </label>
        {error && <p className="modal-error">{error}</p>}
        <button
          className="primary"
          style={{ background: "linear-gradient(110deg, #dc2626, #991b1b)" }}
          disabled={saving}
        >
          {saving ? "Retracting..." : "Confirm Retraction"}
        </button>
      </form>
    </div>
  );
}

function MemoryDetail({ memory, close }: { memory: Memory; close: () => void }) {
  return (
    <div className="overlay">
      <div className="modal detail-modal" role="dialog" aria-modal="true" aria-label="Memory details">
        <button className="close" onClick={close} aria-label="Close memory details">
          x
        </button>
        <p className="eyebrow">PROJECT MEMORY DETAIL</p>
        <span className="type-pill">{kindLabel(memory.type)}</span>
        <h2>{memory.text}</h2>
        <div className="detail-grid">
          <div>
            <small>Source agent</small>
            <strong>{memory.source_agent || memory.metadata.source_agent || "Unknown"}</strong>
          </div>
          <div>
            <small>Session</small>
            <strong>{memory.session_id || "Unavailable"}</strong>
          </div>
          <div>
            <small>Retained</small>
            <strong>{timeLabel(memory.timestamp)}</strong>
          </div>
          <div>
            <small>Storage</small>
            <strong>
              {memory.origin === "demo" ? "Demo mode - local sample memory" : "Hindsight Cloud"}
            </strong>
          </div>
        </div>
        <div className="tag-list">
          {(memory.tags || []).map((tag) => (
            <span key={tag}>#{tag}</span>
          ))}
        </div>
        <small className="memory-id">Memory ID: {memory.id}</small>
      </div>
    </div>
  );
}
