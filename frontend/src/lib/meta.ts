import {
  AlertOctagon,
  Boxes,
  FileCode2,
  GitBranch,
  Handshake,
  Rocket,
  ShieldAlert,
  Undo2,
  type LucideIcon,
} from "lucide-react";
import type { MemoryType } from "./api";

export interface TypeMeta {
  label: string;
  short: string;
  color: string;
  icon: LucideIcon;
}

// One fixed colour and icon per memory type, used everywhere (Blueprint §9).
export const TYPE_META: Record<MemoryType, TypeMeta> = {
  decision: { label: "Decision", short: "DEC", color: "#8d7cff", icon: GitBranch },
  security_constraint: { label: "Security", short: "SEC", color: "#ff6b8b", icon: ShieldAlert },
  convention: { label: "Convention", short: "CNV", color: "#5aa9ff", icon: Boxes },
  api_contract: { label: "API contract", short: "API", color: "#35d6c5", icon: FileCode2 },
  incident: { label: "Incident", short: "INC", color: "#ffb454", icon: AlertOctagon },
  failed_approach: { label: "Failed approach", short: "FAIL", color: "#ff8f5e", icon: Undo2 },
  deployment: { label: "Deployment", short: "DEP", color: "#b58cff", icon: Rocket },
  preference: { label: "Preference", short: "PREF", color: "#8fd46b", icon: Handshake },
};

export const MEMORY_TYPES = Object.keys(TYPE_META) as MemoryType[];

export function typeMeta(type: string): TypeMeta {
  return TYPE_META[type as MemoryType] ?? TYPE_META.decision;
}

export function timeAgo(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  const diff = (Date.now() - date.getTime()) / 1000;
  if (Number.isNaN(diff)) return "—";
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  if (diff < 86400 * 30) return `${Math.round(diff / 86400)}d ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function shortDate(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function dateTime(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function ms(value?: number | null): string {
  if (value === null || value === undefined) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
}

export function pct(value?: number | null): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

export function titleCase(value: string): string {
  return value.replace(/[_-]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
