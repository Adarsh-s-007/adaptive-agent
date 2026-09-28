/** App shell: access gate, rail, project switcher, status pills, drawer host. Owner: P1. */
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { type FormEvent, useMemo, useState } from "react";
import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api, hasAccessToken, setAccessToken } from "../api/client";
import type { ProjectSummary } from "../api/types";
import { EmptyState, ErrorCard, Skeleton, StatusPill } from "../components";
import CheckAsk from "../features/check-ask";
import Compare from "../features/compare";
import Inbox from "../features/inbox";
import Memory from "../features/memory";
import RecordDrawer from "../features/memory/RecordDrawer";
import Overview from "../features/overview";
import Projects from "../features/projects";
import Settings from "../features/settings";
import Workspace from "../features/workspace";
import { DrawerContext, ProjectContext } from "./context";

export const NAV = [
  ["overview", "Overview"],
  ["workspace", "Workspace"],
  ["compare", "Compare"],
  ["inbox", "Inbox"],
  ["memory", "Memory"],
  ["check", "Check & Ask"],
  ["settings", "Settings"],
] as const;

export function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });
}

export default function App() {
  const [client] = useState(makeQueryClient);
  const [unlocked, setUnlocked] = useState(hasAccessToken());
  return (
    <QueryClientProvider client={client}>
      {unlocked ? (
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <AppRoutes />
        </BrowserRouter>
      ) : (
        <AccessGate onUnlock={() => setUnlocked(true)} />
      )}
    </QueryClientProvider>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/projects" replace />} />
      <Route path="/projects" element={<Frame><Projects /></Frame>} />
      <Route path="/p/:pid" element={<ProjectFrame />}>
        <Route index element={<Navigate to="overview" replace />} />
        <Route path="overview" element={<Overview />} />
        <Route path="workspace" element={<Workspace />} />
        <Route path="compare" element={<Compare />} />
        <Route path="inbox" element={<Inbox />} />
        <Route path="memory" element={<Memory />} />
        <Route path="check" element={<CheckAsk />} />
        <Route path="settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Frame><EmptyState title="Page not found" /></Frame>} />
    </Routes>
  );
}

function AccessGate({ onUnlock }: { onUnlock: () => void }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<unknown>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setAccessToken(token.trim());
    try {
      await api.get("/projects");
      onUnlock();
    } catch (err) {
      // Anything other than 401 means the token was accepted (e.g. endpoint not built yet).
      if ((err as { status?: number }).status === 401) {
        setAccessToken("");
        setError(err);
      } else onUnlock();
    }
  }
  return (
    <main className="grid min-h-screen place-items-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-3 rounded-lg border border-rule bg-white p-6">
        <h1 className="text-lg font-semibold">ProjectPulse</h1>
        <label className="block text-sm">
          Access token
          <input
            id="access-token"
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="mt-1 w-full rounded border border-rule px-2 py-1.5 font-mono"
            autoFocus
            required
          />
        </label>
        {error ? <ErrorCard error={error} /> : null}
        <button className="w-full rounded bg-accent py-1.5 text-white">Enter</button>
      </form>
    </main>
  );
}

function useProjects() {
  return useQuery({ queryKey: ["projects"], queryFn: () => api.get<ProjectSummary[]>("/projects") });
}

function TopBar({ projectId }: { projectId?: string }) {
  const navigate = useNavigate();
  const projects = useProjects();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-rule bg-white px-4 py-2">
      <span className="font-semibold">ProjectPulse</span>
      <select
        aria-label="Project"
        className="rounded border border-rule px-2 py-1 text-sm"
        value={projectId ?? ""}
        onChange={(e) => navigate(e.target.value ? `/p/${e.target.value}/overview` : "/projects")}
      >
        <option value="">All projects</option>
        {(projects.data ?? []).map((p) => (
          <option key={p.id} value={p.id}>{p.name}</option>
        ))}
      </select>
      <span className="ml-auto flex gap-2">
        <StatusPill label="Hindsight" state={health.data?.hindsight ?? (health.isError ? "down" : "unknown")} />
        <StatusPill label="LLM" state={health.data?.groq ?? (health.isError ? "down" : "unknown")} />
      </span>
    </div>
  );
}

function Frame({ children, projectId }: { children: React.ReactNode; projectId?: string }) {
  return (
    <div className="min-h-screen">
      <TopBar projectId={projectId} />
      <div className="flex">
        {projectId && (
          <nav aria-label="Sections" className="w-44 shrink-0 border-r border-rule bg-white p-2">
            {NAV.map(([path, label]) => (
              <NavLink
                key={path}
                to={`/p/${projectId}/${path}`}
                className={({ isActive }) =>
                  `block rounded px-3 py-1.5 text-sm ${isActive ? "bg-paper font-semibold text-accent" : "text-muted hover:text-ink"}`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
        )}
        <main className="min-w-0 flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}

function ProjectFrame() {
  const { pid = "" } = useParams();
  const projects = useProjects();
  const [drawerId, setDrawerId] = useState<string | null>(null);
  const drawer = useMemo(() => ({ open: setDrawerId, close: () => setDrawerId(null) }), []);
  const project = projects.data?.find((p) => p.id === pid) ?? { id: pid, name: "Project" };

  let body: React.ReactNode = <Outlet />;
  if (projects.isLoading) body = <Skeleton />;
  else if (projects.isError && (projects.error as { status?: number }).status !== 501)
    body = <ErrorCard error={projects.error} onRetry={() => projects.refetch()} />;

  return (
    <ProjectContext.Provider value={{ project, projectId: pid }}>
      <DrawerContext.Provider value={drawer}>
        <Frame projectId={pid}>{body}</Frame>
        {drawerId && <RecordDrawer recordId={drawerId} onClose={drawer.close} />}
      </DrawerContext.Provider>
    </ProjectContext.Provider>
  );
}
