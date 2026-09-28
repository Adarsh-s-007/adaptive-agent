/** App-wide context: current project and the Record drawer (contract C-10). Owner: P1. */
import { createContext, useContext } from "react";
import type { ProjectSummary } from "../api/types";

export type ProjectCtx = { project: ProjectSummary; projectId: string };
export const ProjectContext = createContext<ProjectCtx | null>(null);

/** Current project inside /p/:pid/* routes. */
export function useProject(): ProjectCtx {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error("useProject() used outside a project route");
  return ctx;
}

export type DrawerCtx = { open: (recordId: string) => void; close: () => void };
export const DrawerContext = createContext<DrawerCtx>({ open: () => {}, close: () => {} });

/** Any feature can open the provenance drawer for a record id. */
export function useRecordDrawer(): DrawerCtx {
  return useContext(DrawerContext);
}
