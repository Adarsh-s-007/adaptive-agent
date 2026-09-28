import { diffLines } from "diff";
import { motion } from "framer-motion";
import {
  Activity,
  ArrowRight,
  BookOpen,
  Download,
  GitCompareArrows,
  History,
  Inbox,
  Layers,
  RefreshCw,
  ShieldCheck,
  Timer,
  TrendingDown,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Button, EmptyState, ErrorCard, Markdown, Modal, ProvenancePill, Skeleton, SkeletonList, Stat, StatusPill, useToast } from "../components/ui";
import { api } from "../lib/api";
import { keys, useInvalidateProject, useMutation, usePid, useProject, useQuery } from "../lib/hooks";
import { dateTime, MEMORY_TYPES, ms, timeAgo, typeMeta } from "../lib/meta";

export default function OverviewPage() {
  const pid = usePid();
  const project = useProject(pid);
  const metrics = useQuery({ queryKey: keys.metrics(pid), queryFn: () => api.metrics(pid), enabled: !!pid });
  const timeline = useQuery({ queryKey: keys.timeline(pid), queryFn: () => api.timeline(pid), enabled: !!pid });
  const m = metrics.data;
  const p = project.data;

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="page-head">
        <div>
          <div className="eyebrow">Overview</div>
          <h1>{p?.name ?? <Skeleton w={200} h={28} />}</h1>
          <p>{p?.description}</p>
        </div>
        <div className="row wrap">
          <Link to={`/p/${pid}/inbox`}><Button icon={Inbox}>Review inbox{p?.stats.pending_candidates ? ` (${p.stats.pending_candidates})` : ""}</Button></Link>
          <Link to={`/p/${pid}/compare`}><Button variant="primary" icon={GitCompareArrows}>Run Compare</Button></Link>
        </div>
      </div>

      <div className="grid-4">
        <Stat label="Active rules" value={m?.records.active} icon={ShieldCheck} sub={m ? `${m.records.superseded} superseded · ${m.records.retracted} retracted` : undefined} />
        <Stat label="Violation delta (median)" value={m?.violation_delta.median ?? null} decimals={1} icon={TrendingDown} accent="var(--teal)" sub={m?.violation_delta.last_10.length ? `over ${m.violation_delta.last_10.length} comparisons` : "run Compare to measure"} />
        <Stat label="Recall latency p50" value={m?.latency.recall_p50_ms ?? null} suffix=" ms" icon={Timer} accent="var(--blue)" sub={m?.latency.samples ? `p95 ${ms(m.latency.recall_p95_ms)} · ${m.latency.samples} recalls` : "no recalls yet"} />
        <Stat label="Isolation violations" value={m?.isolation_violations_blocked ?? 0} icon={Layers} accent={m?.isolation_violations_blocked ? "var(--red)" : "var(--green)"} sub="blocked foreign results (expected 0)" />
      </div>

      <div className="grid-2" style={{ gridTemplateColumns: "minmax(0,1.35fr) minmax(0,1fr)" }}>
        <RulebookCard pid={pid} />
        <div className="stack" style={{ gap: 16 }}>
          <div className="card">
            <div className="card-head"><h3><Layers /> Memory composition</h3><span className="tiny faint">{m?.records.active ?? 0} active</span></div>
            {!m ? <SkeletonList rows={4} h={18} /> : (
              <div className="stack" style={{ gap: 9 }}>
                {MEMORY_TYPES.map((t, i) => {
                  const n = m.records.by_type[t] ?? 0;
                  const max = Math.max(1, ...Object.values(m.records.by_type));
                  const meta = typeMeta(t);
                  return (
                    <div key={t} className="row" style={{ gap: 10 }}>
                      <meta.icon size={14} style={{ color: meta.color }} />
                      <span className="small" style={{ width: 110 }}>{meta.label}</span>
                      <div style={{ flex: 1, height: 8, borderRadius: 8, background: "#161b36", overflow: "hidden" }}>
                        <motion.div initial={{ width: 0 }} animate={{ width: `${(n / max) * 100}%` }} transition={{ delay: i * 0.05, duration: 0.8, ease: [0.22, 1, 0.36, 1] }} style={{ height: "100%", background: meta.color, boxShadow: `0 0 12px ${meta.color}` }} />
                      </div>
                      <span className="small mono" style={{ width: 22, textAlign: "right" }}>{n}</span>
                    </div>
                  );
                })}
                <div className="row tiny faint" style={{ marginTop: 4 }}>
                  <span>{m.records.unsynced} waiting to sync</span>·<span>{m.records.review_due} review due</span>·<span>{m.records.tentative} tentative</span>
                </div>
              </div>
            )}
          </div>
          <div className="card">
            <div className="card-head"><h3><Activity /> Recent activity</h3><Link to={`/p/${pid}/memory?view=timeline`} className="tiny muted">Timeline →</Link></div>
            {timeline.isLoading && <SkeletonList rows={4} h={36} />}
            {timeline.data && timeline.data.length === 0 && <div className="muted small">No activity yet.</div>}
            <div className="list">
              {(timeline.data ?? []).slice(0, 7).map((item) => (
                <div key={item.id} className="row" style={{ gap: 10, alignItems: "flex-start" }}>
                  <span className="pill" style={{ minWidth: 92, justifyContent: "center" }}>{item.kind.replace("_", " ")}</span>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="small strong clip">{item.title}</div>
                    <div className="tiny faint clip">{item.summary}</div>
                  </div>
                  {item.record && <ProvenancePill record={item.record} showArea={false} />}
                  <span className="tiny faint nowrap">{timeAgo(item.at)}</span>
                </div>
              ))}
            </div>
          </div>
          {m && m.violation_delta.last_10.length > 0 && (
            <div className="card">
              <div className="card-head"><h3><GitCompareArrows /> Last comparisons</h3></div>
              <div className="list">
                {m.violation_delta.last_10.slice(0, 5).map((c) => (
                  <div key={c.comparison_id} className="row small">
                    <span className="clip" style={{ flex: 1 }}>{c.task}</span>
                    <span className="mono" style={{ color: "var(--red)" }}>{c.baseline}</span>
                    <ArrowRight size={12} className="faint" />
                    <span className="mono" style={{ color: "var(--green)" }}>{c.memory}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
      {project.error && <ErrorCard error={project.error} onRetry={() => project.refetch()} />}
    </div>
  );
}

function RulebookCard({ pid }: { pid: string }) {
  const rb = useQuery({
    queryKey: keys.rulebook(pid),
    queryFn: () => api.rulebook(pid),
    enabled: !!pid,
    refetchInterval: (q) => (q.state.data?.status === "generating" ? 4000 : false),
  });
  const history = useQuery({ queryKey: keys.rulebookHistory(pid), queryFn: () => api.rulebookHistory(pid), enabled: !!pid });
  const invalidate = useInvalidateProject();
  const toast = useToast();
  const [diffOpen, setDiffOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const refresh = useMutation({
    mutationFn: () => api.refreshRulebook(pid),
    onSuccess: () => { toast.info("Hindsight is re-synthesising the Rulebook from active memory…"); setTimeout(() => invalidate(pid), 6000); setTimeout(() => invalidate(pid), 15000); },
    onError: (e) => toast.error(e),
  });
  const data = rb.data;
  return (
    <div className="card glow" style={{ minHeight: 420 }}>
      <div className="card-head">
        <h2><BookOpen /> Project Rulebook</h2>
        <div className="row">
          {data && <StatusPill tone={data.status === "ready" ? "ok" : data.status === "generating" ? "warn" : "bad"} label={data.status === "ready" ? `refreshed ${timeAgo(data.last_refreshed_at)}` : data.status} live={data.status === "generating"} />}
          <Button size="sm" variant="ghost" icon={History} disabled={(history.data?.length ?? 0) < 2} onClick={() => setDiffOpen(true)}>What changed</Button>
          <Button size="sm" variant="ghost" icon={Download} onClick={() => setExportOpen(true)}>Export</Button>
          <Button size="sm" icon={RefreshCw} loading={refresh.isPending} onClick={() => refresh.mutate()}>Refresh</Button>
        </div>
      </div>
      <div className="tiny faint" style={{ marginBottom: 10 }}>A Hindsight mental model over this project's active, reviewed records. It refreshes after consolidation; superseded rules are excluded.</div>
      {rb.isLoading && <SkeletonList rows={6} h={20} />}
      {rb.error && <ErrorCard error={rb.error} onRetry={() => rb.refetch()} />}
      {data && !data.content && (
        <EmptyState icon={BookOpen} title={data.status === "generating" ? "Synthesising…" : "No rulebook yet"}>
          {data.message ?? "Memory forms from your sessions — import one or start working. The Rulebook appears after the first approvals."}
        </EmptyState>
      )}
      {data?.content && (
        <div style={{ maxHeight: 560, overflowY: "auto", paddingRight: 6 }}>
          {data.source === "cache" && <div className="callout warn small" style={{ marginBottom: 10 }}>Showing the cached copy from {dateTime(data.last_refreshed_at)}. {data.message}</div>}
          <Markdown text={data.content} />
        </div>
      )}
      <Modal open={diffOpen} onClose={() => setDiffOpen(false)} width={900}>
        <h2>What changed in the Rulebook</h2>
        <p className="muted small">Latest synthesis compared with the previous one. Green lines are new; struck lines were removed.</p>
        {history.data && history.data.length >= 2 && (
          <>
            <div className="row tiny muted" style={{ margin: "8px 0" }}>{dateTime(history.data[1].changed_at)} → {dateTime(history.data[0].changed_at)}</div>
            <div className="code-block diff" style={{ maxHeight: "60vh", overflowY: "auto" }}>
              {diffLines(history.data[1].content, history.data[0].content).map((part, i) => (
                <span key={i} className={part.added ? "add" : part.removed ? "del" : ""}>{part.value}</span>
              ))}
            </div>
          </>
        )}
      </Modal>
      <ExportModal open={exportOpen} onClose={() => setExportOpen(false)} pid={pid} />
    </div>
  );
}

function ExportModal({ open, onClose, pid }: { open: boolean; onClose: () => void; pid: string }) {
  const [format, setFormat] = useState<"claude_md" | "cursorrules">("claude_md");
  const q = useQuery({ queryKey: ["export", pid, format], queryFn: () => api.exportRulebook(pid, format), enabled: open });
  const toast = useToast();
  const download = () => {
    if (!q.data) return;
    const blob = new Blob([q.data.content], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = q.data.filename;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return (
    <Modal open={open} onClose={onClose} width={820}>
      <h2>Export the Rulebook</h2>
      <p className="muted small">Complements static rule files instead of competing with them: only active, human-reviewed records, grouped by area, with record IDs.</p>
      <div className="row" style={{ margin: "12px 0" }}>
        <button className={`btn sm ${format === "claude_md" ? "primary" : ""}`} onClick={() => setFormat("claude_md")}>CLAUDE.md</button>
        <button className={`btn sm ${format === "cursorrules" ? "primary" : ""}`} onClick={() => setFormat("cursorrules")}>.cursorrules</button>
        <span className="spacer" />
        <Button size="sm" icon={Download} onClick={download} disabled={!q.data}>Download</Button>
        <Button size="sm" onClick={() => q.data && navigator.clipboard?.writeText(q.data.content).then(() => toast.success("Copied"))}>Copy</Button>
      </div>
      <pre className="code-block" style={{ padding: 14, maxHeight: "55vh", overflow: "auto", fontSize: 12, whiteSpace: "pre-wrap" }}>{q.data?.content ?? "Loading…"}</pre>
    </Modal>
  );
}
