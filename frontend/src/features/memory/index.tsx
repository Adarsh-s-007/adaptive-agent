/** Memory: Library and Timeline (blueprint 9.6). Owner: P3. */
import { useState } from "react";
import { MEMORY_TYPES } from "../../api/types";
import { EmptyState, ErrorCard, PageHeader, ProvenancePill, Skeleton, TypeBadge } from "../../components";
import { useProject } from "../../app/context";
import { useRecords, useTimeline } from "./api";

export default function MemoryScreen() {
  const [view, setView] = useState<"library" | "timeline">("library");
  return (
    <>
      <PageHeader title="Memory">
        <div className="flex gap-1 text-sm">
          {(["library", "timeline"] as const).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setView(v)}
              className={`rounded px-3 py-1 capitalize ${view === v ? "bg-accent text-white" : "border border-rule"}`}
            >
              {v}
            </button>
          ))}
        </div>
      </PageHeader>
      {view === "library" ? <Library /> : <Timeline />}
    </>
  );
}

function Library() {
  const { projectId } = useProject();
  const [filters, setFilters] = useState({ type: "", status: "active", q: "" });
  const records = useRecords(projectId, filters);
  return (
    <>
      <div className="mb-4 flex flex-wrap gap-2 text-sm">
        <input
          id="memory-search"
          aria-label="Search memory"
          placeholder="Search title or rule"
          value={filters.q}
          onChange={(e) => setFilters({ ...filters, q: e.target.value })}
          className="min-w-48 flex-1 rounded border border-rule px-2 py-1"
        />
        <select
          id="memory-type"
          aria-label="Type"
          value={filters.type}
          onChange={(e) => setFilters({ ...filters, type: e.target.value })}
          className="rounded border border-rule px-2 py-1"
        >
          <option value="">All types</option>
          {MEMORY_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select
          id="memory-status"
          aria-label="Status"
          value={filters.status}
          onChange={(e) => setFilters({ ...filters, status: e.target.value })}
          className="rounded border border-rule px-2 py-1"
        >
          <option value="">Any status</option>
          <option value="active">Active</option>
          <option value="superseded">Superseded</option>
          <option value="retracted">Retracted</option>
        </select>
      </div>
      {records.isLoading ? (
        <Skeleton lines={6} />
      ) : records.isError ? (
        <ErrorCard error={records.error} onRetry={() => records.refetch()} />
      ) : !records.data?.length ? (
        <EmptyState title="No memory yet">Memory forms from reviewed sessions. Import a transcript or add a record.</EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-rule bg-white">
          <table className="w-full text-sm">
            <thead className="bg-paper text-left text-xs uppercase text-muted">
              <tr>
                <th className="p-2">Record</th><th className="p-2">Type</th><th className="p-2">Title</th>
                <th className="p-2">Area</th><th className="p-2">Imp.</th><th className="p-2">Status</th>
                <th className="p-2">Decided</th><th className="p-2">Evidence</th><th className="p-2">Sync</th>
              </tr>
            </thead>
            <tbody>
              {records.data.map((r) => (
                <tr key={r.id} className="border-t border-rule">
                  <td className="p-2"><ProvenancePill record={r} /></td>
                  <td className="p-2"><TypeBadge type={r.type} /></td>
                  <td className={`p-2 ${r.status !== "active" ? "text-muted line-through" : ""}`}>{r.title}</td>
                  <td className="p-2 font-mono text-xs">{r.area}</td>
                  <td className="p-2">{r.importance}</td>
                  <td className="p-2">{r.status}</td>
                  <td className="p-2 tabular-nums">{r.decided_at.slice(0, 10)}</td>
                  <td className="p-2">{r.evidence_count}</td>
                  <td className="p-2 text-xs">{r.retain_state === "retained" ? "synced" : "waiting to sync"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function Timeline() {
  const { projectId } = useProject();
  const events = useTimeline(projectId);
  if (events.isLoading) return <Skeleton lines={6} />;
  if (events.isError) return <ErrorCard error={events.error} onRetry={() => events.refetch()} />;
  if (!events.data?.length) return <EmptyState title="No knowledge changes yet" />;
  return (
    <ol className="space-y-2">
      {events.data.map((e) => (
        <li key={e.id} className="flex gap-3 rounded border border-rule bg-white p-3 text-sm">
          <span className="w-24 shrink-0 font-mono text-xs text-muted">{e.event_type}</span>
          <span className="flex-1">{e.record_title ?? "—"}{e.status === "error" && " (failed, will retry)"}</span>
          <time className="tabular-nums text-xs text-muted">{new Date(e.created_at).toLocaleString()}</time>
        </li>
      ))}
    </ol>
  );
}
