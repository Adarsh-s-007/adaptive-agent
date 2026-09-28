/** Shared components. Owner: P1. Features import these; they never edit them. */
import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import type { MemoryType, RecordRef } from "../api/types";
import { useRecordDrawer } from "../app/context";

const TYPE_LABEL: Record<MemoryType, string> = {
  decision: "decision",
  security_constraint: "security",
  convention: "convention",
  api_contract: "api",
  incident: "incident",
  failed_approach: "failed approach",
  deployment: "deployment",
  preference: "preference",
};

const TYPE_CLASS: Record<MemoryType, string> = {
  decision: "text-t-decision border-t-decision/40",
  security_constraint: "text-t-security_constraint border-t-security_constraint/40",
  convention: "text-t-convention border-t-convention/40",
  api_contract: "text-t-api_contract border-t-api_contract/40",
  incident: "text-t-incident border-t-incident/40",
  failed_approach: "text-t-failed_approach border-t-failed_approach/40",
  deployment: "text-t-deployment border-t-deployment/40",
  preference: "text-t-preference border-t-preference/40",
};

export function TypeBadge({ type }: { type: MemoryType }) {
  return (
    <span className={`rounded border px-1.5 py-0.5 font-mono text-[11px] ${TYPE_CLASS[type]}`}>
      {TYPE_LABEL[type]}
    </span>
  );
}

/** "MEM-7F3A · security" — opens the Record drawer. */
export function ProvenancePill({ record }: { record: Pick<RecordRef, "id" | "pill" | "type" | "title"> }) {
  const drawer = useRecordDrawer();
  return (
    <button
      type="button"
      title={record.title}
      onClick={() => drawer.open(record.id)}
      className={`inline-flex items-center gap-1 rounded border bg-white px-1.5 py-0.5 font-mono text-[11px] hover:bg-paper ${TYPE_CLASS[record.type]}`}
    >
      {record.pill} · {TYPE_LABEL[record.type]}
    </button>
  );
}

export function StatusPill({ label, state }: { label: string; state: "ok" | "degraded" | "down" | "unknown" }) {
  const dot = { ok: "bg-emerald-500", degraded: "bg-amber-500", down: "bg-red-500", unknown: "bg-gray-400" }[state];
  const text = { ok: "ready", degraded: "degraded", down: "offline", unknown: "…" }[state];
  return (
    <span className="inline-flex items-center gap-1.5 rounded border border-rule bg-white px-2 py-0.5 text-xs">
      <i className={`h-2 w-2 rounded-full ${dot}`} />
      {label}: {text}
    </span>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-rule p-10 text-center text-muted">
      <p className="font-semibold text-ink">{title}</p>
      {children && <div className="mt-2 text-sm">{children}</div>}
    </div>
  );
}

export function ErrorCard({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const e = error instanceof ApiError ? error : null;
  const message = e?.message ?? (error instanceof Error ? error.message : "Something went wrong.");
  return (
    <div role="alert" className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-900">
      <p className="font-semibold">{message}</p>
      <div className="mt-2 flex items-center gap-3 text-xs">
        {e && <span className="font-mono">{e.code}</span>}
        {e?.requestId && <span className="font-mono">request {e.requestId}</span>}
        {onRetry && (
          <button type="button" onClick={onRetry} className="rounded border border-red-300 px-2 py-0.5">
            Retry
          </button>
        )}
      </div>
    </div>
  );
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-2" aria-busy="true">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="h-4 animate-pulse rounded bg-rule" />
      ))}
    </div>
  );
}

export function PageHeader({ title, owner, children }: { title: string; owner?: string; children?: ReactNode }) {
  return (
    <header className="mb-5 flex items-center justify-between gap-4">
      <h1 className="text-xl font-semibold">
        {title}
        {owner && <span className="ml-2 font-mono text-xs text-muted">{owner}</span>}
      </h1>
      {children}
    </header>
  );
}
