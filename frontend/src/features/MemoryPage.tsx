import { motion } from "framer-motion";
import { Ban, BookmarkPlus, CircleDot, GitMerge, Library, Network, Plus, Search, Sparkles, Timer, Workflow } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useRecordDrawer } from "../components/drawerContext";
import { Button, EmptyState, ErrorCard, Modal, ProvenancePill, RetainState, Segmented, SkeletonList, StatusPill, TypeBadge, useToast } from "../components/ui";
import { api, type MemoryRecord, type TimelineItem } from "../lib/api";
import { keys, useInvalidateProject, useMemories, useMutation, usePid, useQuery } from "../lib/hooks";
import { MEMORY_TYPES, shortDate, timeAgo, typeMeta } from "../lib/meta";

type View = "library" | "timeline" | "constellation";

export default function MemoryPage() {
  const pid = usePid();
  const [params, setParams] = useSearchParams();
  const view = (params.get("view") as View) || "library";
  const [creating, setCreating] = useState(false);
  const setView = (v: View) => { const n = new URLSearchParams(params); n.set("view", v); setParams(n); };
  return (
    <div className="stack" style={{ gap: 18 }}>
      <div className="page-head">
        <div>
          <div className="eyebrow">Memory</div>
          <h1>Everything this project knows</h1>
          <p>Browse and audit reviewed records. PostgreSQL search here is for humans only — agents always recall through Hindsight.</p>
        </div>
        <div className="row">
          <Segmented id="memview" value={view} onChange={setView} options={[{ value: "library", label: "Library", icon: Library }, { value: "timeline", label: "Timeline", icon: Workflow }, { value: "constellation", label: "Constellation", icon: Network }]} />
          <Button variant="primary" icon={Plus} onClick={() => setCreating(true)}>Add record</Button>
        </div>
      </div>
      {view === "library" && <LibraryView pid={pid} />}
      {view === "timeline" && <TimelineView pid={pid} />}
      {view === "constellation" && <ConstellationView pid={pid} />}
      <AddRecordModal open={creating} onClose={() => setCreating(false)} pid={pid} />
    </div>
  );
}

function LibraryView({ pid }: { pid: string }) {
  const q = useMemories(pid);
  const open = useRecordDrawer();
  const [search, setSearch] = useState("");
  const [type, setType] = useState("");
  const [status, setStatus] = useState("active");
  const rows = useMemo(() => (q.data ?? []).filter((r) =>
    (!type || r.type === type) && (status === "all" || r.status === status) &&
    (!search || `${r.pill} ${r.title} ${r.statement} ${r.area}`.toLowerCase().includes(search.toLowerCase()))), [q.data, type, status, search]);
  if (q.isLoading) return <SkeletonList rows={8} h={44} />;
  if (q.error) return <ErrorCard error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data?.length) return <EmptyState icon={Library} title="No memory yet">Memory forms from your sessions — import one in the Workspace, or add a record manually.</EmptyState>;
  return (
    <div className="card flush">
      <div className="row wrap" style={{ padding: 12, borderBottom: "1px solid var(--border)" }}>
        <div className="search" style={{ flex: "1 1 260px" }}><Search /><input className="input" placeholder="Search title, rule, pill…" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        <select className="select" style={{ width: 190 }} value={type} onChange={(e) => setType(e.target.value)}><option value="">All types</option>{MEMORY_TYPES.map((t) => <option key={t} value={t}>{typeMeta(t).label}</option>)}</select>
        <Segmented id="status" value={status} onChange={setStatus} options={[{ value: "active", label: "Active" }, { value: "superseded", label: "Superseded" }, { value: "retracted", label: "Retracted" }, { value: "all", label: "All" }]} />
        <span className="tiny faint">{rows.length} shown</span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="table">
          <thead><tr><th>Record</th><th>Type</th><th style={{ width: "40%" }}>Rule</th><th>Area</th><th>Imp.</th><th>Status</th><th>Decided</th><th>Evidence</th><th>Applied</th><th>Sync</th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <motion.tr key={r.id} className={r.status !== "active" ? "retired" : ""} onClick={() => open(r.id)} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: Math.min(i * 0.02, 0.4) }}>
                <td><ProvenancePill record={r} showArea={false} /></td>
                <td><TypeBadge type={r.type} compact /></td>
                <td><div className="strong small">{r.title}</div><div className={`tiny muted ${r.status !== "active" ? "strike" : ""}`} style={{ marginTop: 2 }}>{r.statement}</div></td>
                <td className="small muted">{r.area ?? "—"}</td>
                <td className="mono small">{"●".repeat(r.importance)}<span className="faint">{"●".repeat(3 - r.importance)}</span></td>
                <td>{r.review_due ? <StatusPill tone="warn" label="review due" /> : <StatusPill tone={r.status === "active" ? "ok" : r.status === "superseded" ? "warn" : "bad"} label={r.status} />}</td>
                <td className="small muted nowrap">{shortDate(r.decided_at)}</td>
                <td className="mono small">{r.evidence_count}</td>
                <td className="mono small">{r.times_applied}{r.times_violated ? <span style={{ color: "var(--red)" }}> / {r.times_violated}✕</span> : null}</td>
                <td><RetainState state={r.retain_state} /></td>
              </motion.tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const KIND: Record<TimelineItem["kind"], { color: string; icon: typeof Sparkles; label: string }> = {
  approved: { color: "var(--green)", icon: BookmarkPlus, label: "Approved" },
  seeded: { color: "var(--violet)", icon: CircleDot, label: "Decided" },
  superseded: { color: "var(--amber)", icon: GitMerge, label: "Superseded" },
  retracted: { color: "var(--red)", icon: Ban, label: "Retracted" },
  session: { color: "var(--blue)", icon: Workflow, label: "Session" },
  rulebook_refreshed: { color: "var(--teal)", icon: Sparkles, label: "Rulebook" },
  comparison: { color: "var(--pink)", icon: Timer, label: "Compare" },
};

function TimelineView({ pid }: { pid: string }) {
  const q = useQuery({ queryKey: keys.timeline(pid), queryFn: () => api.timeline(pid), enabled: !!pid });
  const [filter, setFilter] = useState<string>("all");
  if (q.isLoading) return <SkeletonList rows={8} h={60} />;
  if (q.error) return <ErrorCard error={q.error} onRetry={() => q.refetch()} />;
  const items = (q.data ?? []).filter((i) => filter === "all" || (filter === "memory" ? ["approved", "seeded", "superseded", "retracted"].includes(i.kind) : i.kind === filter));
  return (
    <div className="card">
      <div className="row wrap" style={{ marginBottom: 16 }}>
        <Segmented id="tlf" value={filter} onChange={setFilter} options={[{ value: "all", label: "Everything" }, { value: "memory", label: "Decisions" }, { value: "superseded", label: "Supersessions" }, { value: "session", label: "Sessions" }, { value: "rulebook_refreshed", label: "Rulebook" }]} />
      </div>
      {!items.length && <EmptyState icon={Workflow} title="Nothing here yet">Approvals, supersessions and Rulebook refreshes appear here, newest first.</EmptyState>}
      <div className="timeline">
        {items.map((item, i) => {
          const k = KIND[item.kind];
          return (
            <motion.div key={item.id} className="tl-item" initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: Math.min(i * 0.03, 0.6) }}>
              <span className="tl-node" style={{ borderColor: k.color, color: k.color }}><k.icon /></span>
              <div className="tl-card">
                <div className="row wrap" style={{ gap: 8 }}>
                  <span className="tiny strong" style={{ color: k.color }}>{k.label.toUpperCase()}</span>
                  <span className="strong small">{item.title}</span>
                  <span className="spacer" />
                  <span className="tiny faint">{shortDate(item.at)} · {timeAgo(item.at)}</span>
                </div>
                {item.kind === "superseded" && item.previous && item.record ? (
                  <div className="row wrap" style={{ marginTop: 8, gap: 8 }}>
                    <ProvenancePill record={item.previous} />
                    <span className="small strike clip" style={{ maxWidth: 300 }}>{item.previous.statement}</span>
                    <span className="muted">→</span>
                    <ProvenancePill record={item.record} />
                    <span className="small clip" style={{ maxWidth: 360 }}>{item.record.statement}</span>
                  </div>
                ) : (
                  <div className="row" style={{ marginTop: 6, gap: 8 }}>
                    {item.record && <ProvenancePill record={item.record} />}
                    <span className="small muted clip">{item.summary}</span>
                  </div>
                )}
                {item.actor && <div className="tiny faint" style={{ marginTop: 4 }}>by {item.actor}</div>}
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}

/** A living map of the project's memory: records orbit their area, supersession chains are drawn as arcs. */
function ConstellationView({ pid }: { pid: string }) {
  const q = useMemories(pid);
  const open = useRecordDrawer();
  const [hover, setHover] = useState<MemoryRecord | null>(null);
  const layout = useMemo(() => {
    const recs = q.data ?? [];
    const areas = Array.from(new Set(recs.map((r) => r.area ?? "general"))).sort();
    const W = 1000, H = 560, cx = W / 2, cy = H / 2;
    const R = Math.min(W, H) * 0.34;
    const hubs = areas.map((a, i) => {
      const ang = (i / Math.max(1, areas.length)) * Math.PI * 2 - Math.PI / 2;
      return { area: a, x: cx + Math.cos(ang) * R * 1.15, y: cy + Math.sin(ang) * R * 0.95 };
    });
    const hubOf = Object.fromEntries(hubs.map((h) => [h.area, h]));
    const nodes = recs.map((r) => {
      const hub = hubOf[r.area ?? "general"];
      const siblings = recs.filter((x) => (x.area ?? "general") === (r.area ?? "general"));
      const k = siblings.indexOf(r);
      const ang = (k / Math.max(1, siblings.length)) * Math.PI * 2 + hub.x * 0.01;
      const dist = 42 + (k % 2) * 22 + (r.status === "active" ? 0 : 14);
      return { r, x: hub.x + Math.cos(ang) * dist, y: hub.y + Math.sin(ang) * dist, hub };
    });
    const pos = Object.fromEntries(nodes.map((n) => [n.r.id, n]));
    const links = recs.filter((r) => r.supersedes_id && pos[r.supersedes_id]).map((r) => ({ from: pos[r.supersedes_id!], to: pos[r.id] }));
    return { hubs, nodes, links, W, H, cx, cy };
  }, [q.data]);
  if (q.isLoading) return <SkeletonList rows={1} h={560} />;
  if (!q.data?.length) return <EmptyState icon={Network} title="An empty sky">Records appear here as stars grouped by area once memory forms.</EmptyState>;
  return (
    <div className="constellation">
      <svg viewBox={`0 0 ${layout.W} ${layout.H}`} preserveAspectRatio="xMidYMid meet">
        <defs>
          <radialGradient id="hubglow"><stop offset="0" stopColor="#8d7cff" stopOpacity=".45" /><stop offset="1" stopColor="#8d7cff" stopOpacity="0" /></radialGradient>
        </defs>
        <circle cx={layout.cx} cy={layout.cy} r={16} fill="url(#hubglow)" />
        <text x={layout.cx} y={layout.cy + 4} textAnchor="middle" className="c-area" style={{ fill: "#c9c2ff" }}>BANK</text>
        {layout.hubs.map((h) => (
          <g key={h.area}>
            <line x1={layout.cx} y1={layout.cy} x2={h.x} y2={h.y} stroke="#2a3160" strokeDasharray="3 6" style={{ animation: "dash 3s linear infinite" }} />
            <circle cx={h.x} cy={h.y} r={70} fill="url(#hubglow)" opacity={0.5} />
            <text x={h.x} y={h.y - 78} textAnchor="middle" className="c-area">{h.area}</text>
          </g>
        ))}
        {layout.links.map((l, i) => (
          <path key={i} d={`M${l.from.x},${l.from.y} Q${(l.from.x + l.to.x) / 2},${Math.min(l.from.y, l.to.y) - 40} ${l.to.x},${l.to.y}`} fill="none" stroke="#ffb454" strokeWidth={1.5} strokeDasharray="4 4" opacity={0.8} />
        ))}
        {layout.nodes.map(({ r, x, y }, i) => {
          const meta = typeMeta(r.type);
          const size = 5 + r.importance * 2.5 + Math.min(6, r.times_applied);
          return (
            <motion.g key={r.id} className="c-node" initial={{ opacity: 0, scale: 0 }} animate={{ opacity: r.status === "active" ? 1 : 0.35, scale: 1 }} transition={{ delay: i * 0.03, type: "spring" }}
              onMouseEnter={() => setHover(r)} onMouseLeave={() => setHover(null)} onClick={() => open(r.id)} style={{ transformOrigin: `${x}px ${y}px` }}>
              <circle cx={x} cy={y} r={size * 2.4} fill={meta.color} opacity={0.12} />
              <circle className="core" cx={x} cy={y} r={size} fill={meta.color} style={{ filter: `drop-shadow(0 0 8px ${meta.color})` }} />
              {r.status !== "active" && <line x1={x - size - 3} y1={y} x2={x + size + 3} y2={y} stroke="#ff5c78" strokeWidth={1.5} />}
              <text x={x} y={y + size + 12} textAnchor="middle" className="c-label">{r.pill}</text>
            </motion.g>
          );
        })}
      </svg>
      {hover && (
        <div className="card tight" style={{ position: "absolute", left: 16, bottom: 16, maxWidth: 420, pointerEvents: "none" }}>
          <div className="row"><TypeBadge type={hover.type} /><span className="strong small">{hover.title}</span></div>
          <div className="small muted" style={{ marginTop: 6 }}>{hover.statement}</div>
          <div className="tiny faint" style={{ marginTop: 4 }}>{hover.status} · decided {shortDate(hover.decided_at)} · applied {hover.times_applied}×</div>
        </div>
      )}
      <div className="row wrap tiny" style={{ position: "absolute", right: 14, top: 12, gap: 10 }}>
        {MEMORY_TYPES.map((t) => <span key={t} className="row" style={{ gap: 4 }}><span style={{ width: 8, height: 8, borderRadius: 8, background: typeMeta(t).color }} />{typeMeta(t).label}</span>)}
        <span className="row" style={{ gap: 4, color: "var(--amber)" }}>┈ supersedes</span>
      </div>
    </div>
  );
}

function AddRecordModal({ open, onClose, pid }: { open: boolean; onClose: () => void; pid: string }) {
  const [form, setForm] = useState({ title: "", statement: "", rationale: "", type: "decision", area: "", applies_to: "", evidence_quote: "", reviewer: "Tech lead" });
  const invalidate = useInvalidateProject();
  const toast = useToast();
  const m = useMutation({
    mutationFn: () => api.createMemory(pid, { ...form, applies_to: form.applies_to.split(",").map((s) => s.trim()).filter(Boolean) }),
    onSuccess: (r) => { toast.success(`${r.pill} created — ${r.retain_state === "retained" ? "retained into Hindsight" : "waiting to sync"}.`); invalidate(pid); onClose(); },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal open={open} onClose={onClose}>
      <h2>Add a record</h2>
      <p className="muted small">Human-authored records are confidence 1.0 and go through the same validator and retain path as approvals.</p>
      <div className="stack" style={{ marginTop: 12 }}>
        <label className="field"><span>Title</span><input className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
        <label className="field"><span>Rule</span><textarea className="textarea" value={form.statement} onChange={(e) => setForm({ ...form, statement: e.target.value })} placeholder="Imperative, one atomic rule" /></label>
        <label className="field"><span>Rationale</span><input className="input" value={form.rationale} onChange={(e) => setForm({ ...form, rationale: e.target.value })} /></label>
        <div className="grid-3">
          <label className="field"><span>Type</span><select className="select" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>{MEMORY_TYPES.map((t) => <option key={t} value={t}>{typeMeta(t).label}</option>)}</select></label>
          <label className="field"><span>Area</span><input className="input" value={form.area} onChange={(e) => setForm({ ...form, area: e.target.value })} /></label>
          <label className="field"><span>Applies to</span><input className="input" value={form.applies_to} onChange={(e) => setForm({ ...form, applies_to: e.target.value })} placeholder="login, app/api/**" /></label>
        </div>
        <div className="row"><span className="spacer" /><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={m.isPending} disabled={form.title.length < 3 || form.statement.length < 15} onClick={() => m.mutate()}>Create & retain</Button></div>
      </div>
    </Modal>
  );
}
