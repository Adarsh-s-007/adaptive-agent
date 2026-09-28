import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  Brain,
  ChevronsUpDown,
  CircuitBoard,
  FolderKanban,
  GitCompareArrows,
  Inbox,
  KeyRound,
  LayoutDashboard,
  Library,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  WifiOff,
} from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { NavLink, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { RecordDrawer } from "../components/RecordDrawer";
import { Button, Kbd, StatusPill, ToastProvider } from "../components/ui";
import { ApiError, onAuthError, setAccessToken } from "../lib/api";
import { useInbox, useProject, useProjects, useQueryClient, useStatus } from "../lib/hooks";
import { hasWebGL } from "../three/support";
import { emitScene } from "../three/bus";
import CheckAskPage from "../features/CheckAskPage";
import ComparePage from "../features/ComparePage";
import InboxPage from "../features/InboxPage";
import MemoryPage from "../features/MemoryPage";
import OverviewPage from "../features/OverviewPage";
import ProjectsPage from "../features/ProjectsPage";
import SettingsPage from "../features/SettingsPage";
import WorkspacePage from "../features/WorkspacePage";

const SceneBackground = lazy(() => import("../three/SceneBackground"));

export default function App() {
  const [needsToken, setNeedsToken] = useState(false);
  const show3d = useMemo(() => hasWebGL() && !navigator.userAgent.includes("jsdom"), []);
  useEffect(() => {
    const off = onAuthError(() => setNeedsToken(true));
    return () => { off(); };
  }, []);
  return (
    <ToastProvider>
      {show3d && <Suspense fallback={null}><SceneBackground /></Suspense>}
      {needsToken ? (
        <AccessGate onDone={() => setNeedsToken(false)} />
      ) : (
        <Routes>
          <Route path="/" element={<Frame><ProjectsPage /></Frame>} />
          <Route path="/p/:pid/*" element={<ProjectFrame />} />
          <Route path="*" element={<Frame><ProjectsPage /></Frame>} />
        </Routes>
      )}
    </ToastProvider>
  );
}

function ProjectFrame() {
  const location = useLocation();
  return (
    <Frame>
      <AnimatePresence mode="wait">
        <motion.div key={location.pathname.split("/").slice(0, 4).join("/")} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}>
          <Routes>
            <Route index element={<OverviewPage />} />
            <Route path="workspace" element={<WorkspacePage />} />
            <Route path="workspace/:sid" element={<WorkspacePage />} />
            <Route path="compare" element={<ComparePage />} />
            <Route path="inbox" element={<InboxPage />} />
            <Route path="memory" element={<MemoryPage />} />
            <Route path="check" element={<CheckAskPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Routes>
        </motion.div>
      </AnimatePresence>
      <RecordDrawer />
    </Frame>
  );
}

// ---------------------------------------------------------------- frame
function Frame({ children }: { children: React.ReactNode }) {
  const params = useParams();
  const location = useLocation();
  const pid = params.pid ?? location.pathname.match(/^\/p\/([^/]+)/)?.[1] ?? "";
  const [palette, setPalette] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="shell">
      <Rail pid={pid} onSearch={() => setPalette(true)} />
      <div className="main">
        <TopBar pid={pid} onSearch={() => setPalette(true)} />
        <Banners pid={pid} />
        <main className="content">{children}</main>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} pid={pid} />
    </div>
  );
}

const NAV = [
  { to: "", label: "Overview", icon: LayoutDashboard },
  { to: "workspace", label: "Workspace", icon: TerminalSquare },
  { to: "compare", label: "Compare", icon: GitCompareArrows },
  { to: "inbox", label: "Inbox", icon: Inbox },
  { to: "memory", label: "Memory", icon: Library },
  { to: "check", label: "Check & Ask", icon: ShieldCheck },
  { to: "settings", label: "Settings", icon: Settings },
];

function Rail({ pid, onSearch }: { pid: string; onSearch: () => void }) {
  const inbox = useInbox(pid);
  const pending = inbox.data?.counts.pending ?? 0;
  const location = useLocation();
  return (
    <nav className="rail" aria-label="Primary">
      <NavLink to="/" className="brand">
        <span className="brand-mark" data-anchor="brand">✦</span>
        <span>
          <b>Project<span>Pulse</span></b>
          <small>governed memory</small>
        </span>
      </NavLink>
      <NavLink to="/" end className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
        {location.pathname === "/" && <motion.span layoutId="nav-bg" className="nav-active-bg" />}
        <FolderKanban /><span className="label">Projects</span>
      </NavLink>
      {pid && (
        <>
          <div className="rail-section">Project</div>
          {NAV.map((item) => {
            const path = `/p/${pid}${item.to ? `/${item.to}` : ""}`;
            const active = item.to ? location.pathname.startsWith(path) : location.pathname === path;
            return (
              <NavLink key={item.label} to={path} end={!item.to} className={() => `nav-link ${active ? "active" : ""}`}>
                {active && <motion.span layoutId="nav-bg" className="nav-active-bg" transition={{ type: "spring", bounce: 0.2, duration: 0.5 }} />}
                <item.icon /><span className="label">{item.label}</span>
                {item.label === "Inbox" && pending > 0 && <span className="nav-badge">{pending}</span>}
              </NavLink>
            );
          })}
        </>
      )}
      <div className="rail-footer">
        <button className="btn sm ghost" style={{ justifyContent: "flex-start" }} onClick={onSearch}><Search /> Search <span className="spacer" /><Kbd>Ctrl K</Kbd></button>
        <div className="tiny faint" style={{ padding: "0 6px" }}>Memory by <span className="gradient-text strong">Hindsight</span></div>
      </div>
    </nav>
  );
}

function TopBar({ pid, onSearch }: { pid: string; onSearch: () => void }) {
  const status = useStatus();
  const project = useProject(pid);
  const projects = useProjects();
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const hs = status.data?.hindsight.status;
  const llm = status.data?.llm.status;
  useEffect(() => {
    emitScene({ type: "health", value: hs === "ok" ? "connected" : hs === "offline" || hs === "down" ? "offline" : "unknown" });
  }, [hs]);
  const hsTone = !status.data ? "none" : hs === "ok" ? "ok" : hs === "offline" ? "warn" : "bad";
  const llmTone = !status.data ? "none" : llm === "ok" ? "ok" : llm === "unconfigured" ? "warn" : "bad";
  return (
    <header className="topbar">
      {pid ? (
        <div style={{ position: "relative" }}>
          <button className="btn ghost" onClick={() => setOpen(!open)} style={{ paddingLeft: 8 }}>
            <span className="brand-mark" style={{ width: 24, height: 24, fontSize: 12, borderRadius: 7 }}>{project.data?.name?.[0] ?? "·"}</span>
            <span className="strong" style={{ fontSize: 14 }}>{project.data?.name ?? "Loading…"}</span>
            <ChevronsUpDown />
          </button>
          <AnimatePresence>
            {open && (
              <motion.div className="card" style={{ position: "absolute", top: 44, left: 0, width: 300, zIndex: 40, padding: 6 }} initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} onMouseLeave={() => setOpen(false)}>
                {(projects.data ?? []).map((p) => (
                  <button key={p.id} className="btn ghost" style={{ width: "100%", justifyContent: "flex-start" }} onClick={() => { setOpen(false); navigate(location.pathname.replace(/^\/p\/[^/]+/, `/p/${p.id}`).replace(/\/workspace\/[^/]+$/, "/workspace")); }}>
                    <span className="brand-mark" style={{ width: 20, height: 20, fontSize: 10, borderRadius: 6 }}>{p.name[0]}</span>
                    <span className="clip">{p.name}</span>
                    <span className="spacer" />
                    <span className="tiny faint">{p.stats.active_records} rules</span>
                  </button>
                ))}
                <div className="divider" style={{ margin: "6px 0" }} />
                <button className="btn ghost sm" style={{ width: "100%" }} onClick={() => navigate("/")}>All projects</button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      ) : (
        <span className="strong">Projects</span>
      )}
      {project.data && <span className="bank-id" title="This project's isolated Hindsight bank">{project.data.bank_id}</span>}
      <span className="spacer" />
      <button className="btn sm ghost" onClick={onSearch}><Search /> <Kbd>Ctrl K</Kbd></button>
      <span data-anchor="beacon" style={{ width: 8, height: 8, display: "inline-block" }} />
      <StatusPill tone={hsTone} live={hs === "ok"} icon={Brain} label={<>Hindsight: {hs === "ok" ? "ready" : hs === "offline" ? "forced offline" : hs ?? "…"}{status.data?.hindsight.latency_ms ? <span className="faint"> · {status.data.hindsight.latency_ms}ms</span> : null}</>} />
      <StatusPill tone={llmTone} icon={CircuitBoard} label={<>LLM: {llm === "ok" ? "ready" : llm === "unconfigured" ? "not configured" : llm ?? "…"}</>} />
    </header>
  );
}

function Banners({ pid }: { pid: string }) {
  const status = useStatus();
  const project = useProject(pid);
  const hs = status.data?.hindsight.status;
  const llm = status.data?.llm.status;
  return (
    <>
      {status.error instanceof ApiError && status.error.code === "NETWORK" && (
        <div className="banner bad"><WifiOff /><span>Service unavailable — retrying. Start the API with <code>uvicorn app.main:app --port 8000</code>.</span></div>
      )}
      {hs && hs !== "ok" && (
        <div className="banner bad"><AlertTriangle /><span>Hindsight is {hs === "offline" ? "forced offline" : "unreachable"}: Brief, Check and Ask are unavailable, approvals queue as “Waiting to sync”, baseline runs still work. Nothing pretends memory was used.</span></div>
      )}
      {llm && llm !== "ok" && (
        <div className="banner warn"><KeyRound /><span>No LLM configured (set <code>GROQ_API_KEY</code>). Memory, recall, review and Ask work; generation and Compare are disabled; extraction, filtering and Check use labelled deterministic heuristics.</span></div>
      )}
      {project.data?.bank_status === "error" && (
        <div className="banner bad"><AlertTriangle /><span>This project's Hindsight bank is not ready: {project.data.bank_error}. Reprovision it in Settings.</span></div>
      )}
    </>
  );
}

// ---------------------------------------------------------------- palette
function CommandPalette({ open, onClose, pid }: { open: boolean; onClose: () => void; pid: string }) {
  const navigate = useNavigate();
  const projects = useProjects();
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const qc = useQueryClient();
  const items = useMemo(() => {
    const list: { label: string; icon: typeof Search; go: () => void; hint?: string }[] = [];
    if (pid) NAV.forEach((n) => list.push({ label: `Go to ${n.label}`, icon: n.icon, go: () => navigate(`/p/${pid}${n.to ? `/${n.to}` : ""}`) }));
    (projects.data ?? []).forEach((p) => list.push({ label: `Open project ${p.name}`, icon: FolderKanban, hint: p.bank_id, go: () => navigate(`/p/${p.id}`) }));
    list.push({ label: "All projects", icon: FolderKanban, go: () => navigate("/") });
    list.push({ label: "Refresh data", icon: Sparkles, go: () => void qc.invalidateQueries() });
    return list.filter((i) => i.label.toLowerCase().includes(q.toLowerCase()));
  }, [pid, projects.data, q, navigate, qc]);
  useEffect(() => { setIdx(0); }, [q, open]);
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div className="overlay" style={{ zIndex: 89 }} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <motion.div className="palette" initial={{ opacity: 0, y: -12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -8 }}>
            <input
              autoFocus
              placeholder="Jump to a screen or project…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(items.length - 1, i + 1)); }
                if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(0, i - 1)); }
                if (e.key === "Enter" && items[idx]) { items[idx].go(); onClose(); }
                if (e.key === "Escape") onClose();
              }}
            />
            <div className="items">
              {items.map((item, i) => (
                <div key={item.label} className={`item ${i === idx ? "active" : ""}`} onMouseEnter={() => setIdx(i)} onClick={() => { item.go(); onClose(); }}>
                  <item.icon /> {item.label} <span className="spacer" />{item.hint && <span className="tiny faint mono">{item.hint}</span>}
                </div>
              ))}
              {!items.length && <div className="item muted">No matches</div>}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

// ---------------------------------------------------------------- gate
function AccessGate({ onDone }: { onDone: () => void }) {
  const [token, setToken] = useState("");
  const qc = useQueryClient();
  return (
    <div className="gate">
      <motion.div className="card glow" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
        <div className="brand" style={{ padding: 0, marginBottom: 18 }}>
          <span className="brand-mark">✦</span>
          <span><b>Project<span>Pulse</span></b><small>access required</small></span>
        </div>
        <h2 style={{ margin: "0 0 6px" }}>Enter the access token</h2>
        <p className="muted small">This deployment is protected by a shared access token. It is kept for this browser tab only.</p>
        <form onSubmit={(e) => { e.preventDefault(); setAccessToken(token.trim()); onDone(); void qc.invalidateQueries(); }} className="stack" style={{ marginTop: 14 }}>
          <input className="input" type="password" autoFocus placeholder="APP_ACCESS_TOKEN" value={token} onChange={(e) => setToken(e.target.value)} />
          <Button variant="primary" icon={KeyRound} disabled={token.trim().length < 4}>Unlock</Button>
        </form>
      </motion.div>
    </div>
  );
}
