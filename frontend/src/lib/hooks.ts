import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "./api";

export const keys = {
  status: ["status"] as const,
  projects: ["projects"] as const,
  project: (pid: string) => ["project", pid] as const,
  sessions: (pid: string) => ["sessions", pid] as const,
  session: (pid: string, sid: string) => ["session", pid, sid] as const,
  inbox: (pid: string) => ["inbox", pid] as const,
  memories: (pid: string) => ["memories", pid] as const,
  memory: (pid: string, rid: string) => ["memory", pid, rid] as const,
  timeline: (pid: string) => ["timeline", pid] as const,
  metrics: (pid: string) => ["metrics", pid] as const,
  rulebook: (pid: string) => ["rulebook", pid] as const,
  rulebookHistory: (pid: string) => ["rulebook-history", pid] as const,
  comparisons: (pid: string) => ["comparisons", pid] as const,
  bank: (pid: string) => ["bank", pid] as const,
  audit: (pid: string) => ["audit", pid] as const,
  evals: (pid: string) => ["evals", pid] as const,
  demoTasks: ["demo-tasks"] as const,
};

export function usePid(): string {
  return useParams().pid ?? "";
}

export function useStatus() {
  return useQuery({ queryKey: keys.status, queryFn: api.status, refetchInterval: 30_000, retry: 1 });
}

export function useProjects() {
  return useQuery({ queryKey: keys.projects, queryFn: api.projects });
}

export function useProject(pid: string) {
  return useQuery({
    queryKey: keys.project(pid),
    queryFn: () => api.project(pid),
    enabled: !!pid,
    refetchInterval: (q) => (q.state.data?.bank_status === "provisioning" ? 1500 : 20_000),
  });
}

export function useInbox(pid: string) {
  return useQuery({ queryKey: keys.inbox(pid), queryFn: () => api.inbox(pid), enabled: !!pid });
}

export function useMemories(pid: string) {
  return useQuery({ queryKey: keys.memories(pid), queryFn: () => api.memories(pid), enabled: !!pid });
}

export function useDemoTasks() {
  return useQuery({ queryKey: keys.demoTasks, queryFn: api.demoTasks, staleTime: Infinity });
}

/** Invalidate everything that changes when memory changes. */
export function useInvalidateProject() {
  const qc = useQueryClient();
  return (pid: string) => {
    for (const key of [
      keys.project(pid), keys.inbox(pid), keys.memories(pid), keys.timeline(pid), keys.metrics(pid),
      keys.sessions(pid), keys.rulebook(pid), keys.rulebookHistory(pid), keys.projects, keys.audit(pid),
    ]) {
      void qc.invalidateQueries({ queryKey: key });
    }
    void qc.invalidateQueries({ queryKey: ["memory", pid] });
    void qc.invalidateQueries({ queryKey: ["session", pid] });
  };
}

export { useMutation, useQuery, useQueryClient };
